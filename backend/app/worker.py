import json
import logging
import signal
import threading
import time
from sqlalchemy import delete, update
from .db import DB, Device, Event, Command, Measurement, Session, AutomationRun, WorkflowRun, health
from .events import ingest, process_one
from .tuya import TuyaHTTP, DurablePulsar
from .config import CALLS_PER_MINUTE, RECONCILE_SECONDS

logger = logging.getLogger("worker")


def reconcile(api, stop=None):
    with DB() as db:
        devices = db.query(Device).all()
    failures = 0
    for device in devices:
        # Remote IR IDs are not generic Tuya devices. Only synchronize real hubs/sensors.
        if device.config.get("command", {}).get("kind") == "ir" and not device.config.get('properties'):
            continue
        try:
            detail = api.read_status(device)
        except Exception as exc:
            failures += 1
            health("reconcile", {"ok": False, "error": type(exc).__name__, "device": device.id})
            if stop and stop.wait(60 / max(1, CALLS_PER_MINUTE) + 1):
                return
            continue
        at = time.time()
        ingest({"devId": device.id, "ts": int(at * 1000), "status": detail.get("status", []),
                '_cloud_query_without_time': any(not item.get('t') for item in detail.get('status', []))},
               f"sync:{device.id}:{at}")
        if isinstance(detail.get("online"), bool):
            ingest({"bizCode": "online" if detail["online"] else "offline",
                    "bizData": {"devId": device.id}, "ts": int(at * 1000)}, f"sync-online:{device.id}:{at}")
        if stop and stop.wait(60 / max(1, CALLS_PER_MINUTE) + 1):
            return
    health("reconcile", {"ok": failures == 0, "failures": failures, "at": time.time()})


def sync_loop(api, stop, sync):
    while not stop.is_set():
        if sync.wait(1):
            sync.clear()
            try:
                reconcile(api, stop)
            except Exception as exc:
                health("reconcile", {"ok": False, "error": type(exc).__name__})


def maintenance():
    now = time.time()
    with DB.begin() as db:
        db.execute(delete(Measurement).where(Measurement.observed < now - 90 * 86400))
        db.execute(update(Event).where(Event.status == "processed", Event.received < now - 7 * 86400,
                                      Event.payload_pruned.is_(False)).values(payload={}, payload_pruned=True))
        db.execute(delete(Event).where(Event.status == "processed", Event.received < now - 90 * 86400))
        db.execute(delete(Command).where(Command.created < now - 180 * 86400))
        db.execute(delete(AutomationRun).where(AutomationRun.created < now - 180 * 86400))
        db.execute(delete(WorkflowRun).where(WorkflowRun.created < now - 180 * 86400))
        db.execute(update(WorkflowRun).where(WorkflowRun.status == 'executando', WorkflowRun.updated < now - 60).values(status='resultado desconhecido', updated=now))
        db.execute(update(AutomationRun).where(AutomationRun.status == 'em execução', AutomationRun.created < now - 120).values(status='resultado desconhecido'))
        db.execute(delete(Session).where(Session.expires < now))
        # An interrupted request must never be replayed automatically.
        db.execute(update(Command).where(Command.status == "solicitado", Command.created < now - 60)
                   .values(status="resultado desconhecido", updated=now, response={"error": "interrupted_request"}))


def main():
    logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","message":"%(message)s"}')
    stop, sync = threading.Event(), threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    api = TuyaHTTP()
    consumer = DurablePulsar(sync)
    consumer.start()
    sync_thread = threading.Thread(target=sync_loop, args=(api, stop, sync), daemon=True)
    sync_thread.start()
    sync.set()
    next_sync = next_maintenance = next_automation = 0
    while not stop.is_set():
        try:
            health("worker", {"alive": True})
            for _ in range(100):
                if not process_one():
                    break
            if time.time() >= next_automation:
                from .automations import tick
                tick(api)
                from .workflows import tick as tick_flow
                tick_flow(api)
                next_automation = time.time() + 5
            if time.time() >= next_sync:
                sync.set()
                next_sync = time.time() + RECONCILE_SECONDS
            if time.time() >= next_maintenance:
                maintenance()
                next_maintenance = time.time() + 60
        except Exception as exc:
            logger.error("worker_iteration_failed:%s", type(exc).__name__)
        stop.wait(1)
    consumer.stop()
    consumer.join(timeout=15)
    sync_thread.join(timeout=15)
    api.client.close()


if __name__ == "__main__":
    main()
