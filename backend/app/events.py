import hashlib
import json
import math
import time
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import DB, Device, Event, Measurement, State, health


def ingest(payload, event_id=None):
    key = event_id or payload.get("eventId") or payload.get("dataId")
    key = str(key) if key else hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    try:
        with DB.begin() as db:
            db.add(Event(id=key, payload=payload))
    except IntegrityError:
        # Only acknowledge a duplicate when that exact event is already durable.
        with DB() as db:
            if not db.get(Event, key):
                raise
    health("last_ingest", {"at": time.time()})
    return key


def timestamp(value, default):
    if value is None:
        return default
    result = float(value)
    if result > 1e11:
        result /= 1000
    if not math.isfinite(result) or result < 0 or result > time.time() + 300:
        raise ValueError("invalid_timestamp")
    return result


def normalize(payload, received, cfg):
    data = payload.get("bizData", payload)
    observed = timestamp(data.get("ts", payload.get("ts", payload.get("t"))), received)
    if payload.get("bizCode") in ("online", "offline"):
        yield "online", payload["bizCode"] == "online", "", observed
    for item in data.get("status", []):
        code = item.get("code")
        mapping = cfg.get("properties", {}).get(code)
        if not mapping:
            continue
        value = item["value"]
        kind = mapping.get("type", "number")
        if kind == "number":
            if isinstance(value, bool):
                raise ValueError("boolean_in_numeric_property")
            value = float(value) / (10 ** int(mapping.get("scale", 0)))
            if not math.isfinite(value):
                raise ValueError("non_finite_measurement")
        elif kind == "boolean" and not isinstance(value, bool):
            raise ValueError("invalid_boolean")
        yield mapping["property"], value, mapping.get("unit", ""), timestamp(item.get("t"), observed)


def process_one():
    with DB.begin() as db:
        event = db.execute(select(Event).where(Event.status == "pending", Event.next_attempt <= time.time())
                           .order_by(Event.received).with_for_update(skip_locked=True).limit(1)).scalar_one_or_none()
        if not event:
            return False
        try:
            # Savepoint rolls back all measurements on a partially invalid event.
            with db.begin_nested():
                payload = event.payload
                data = payload.get("bizData", payload)
                device = db.get(Device, data.get("devId", payload.get("devId", "")))
                if not device:
                    raise ValueError("unknown_device")
                for prop, value, unit, observed in normalize(payload, event.received, device.config):
                    db.add(Measurement(event_id=event.id, device_id=device.id, property=prop,
                                       value=value, unit=unit, observed=observed, received=event.received))
                    state = db.get(State, (device.id, prop))
                    if not state or observed >= state.observed:
                        db.merge(State(device_id=device.id, property=prop, value=value, unit=unit,
                                       observed=observed, received=event.received, source="reportado"))
                db.flush()
            event.status, event.error = "processed", None
        except Exception as exc:
            event.attempts += 1
            event.error = type(exc).__name__
            event.next_attempt = time.time() + min(300, 2 ** event.attempts)
            if event.attempts >= 5:
                event.status = "dead"
    return True
