import asyncio
import json
import secrets
import time
from datetime import datetime
from contextlib import asynccontextmanager
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import FastAPI, Request, Response, HTTPException, WebSocket, WebSocketDisconnect, Query, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_
from . import config
from .db import DB, Device, State, Measurement, Event, Command, Session, Health, take_rate
from .security import authenticate, digest
from .commands import submit, serialize
from .tuya import TuyaHTTP
from .weather import outdoor_weather
from .appearance import router as appearance_router
from .controls import router as controls_router
from .automations import router as automations_router
from .workflows import router as workflow_router
from .notifications import router as notification_router
from .control_profiles import capabilities


@asynccontextmanager
async def lifespan(app):
    app.state.tuya = TuyaHTTP()
    yield
    app.state.tuya.client.close()


app = FastAPI(title="Tuya IoT", version="1.0.0", lifespan=lifespan,
              openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", redoc_url=None)
PREFIX = "/api/v1"
app.include_router(appearance_router)
app.include_router(controls_router)
app.include_router(automations_router)
app.include_router(workflow_router)
app.include_router(notification_router)


@app.get(PREFIX + "/weather/current")
def current_weather(request: Request):
    authenticate(request)
    return outdoor_weather()


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1024)


class Power(BaseModel):
    power: bool = Field(strict=True)


@app.post(PREFIX + "/auth/login")
def login(body: Login, request: Request, response: Response):
    if request.headers.get("origin") != config.ORIGIN:
        raise HTTPException(403, "Origem inválida")
    if not take_rate("login", 10):
        raise HTTPException(429, "Aguarde antes de tentar novamente")
    valid = False
    try:
        valid = PasswordHasher().verify(config.secret("ADMIN_PASSWORD_HASH"), body.password)
    except (VerifyMismatchError, InvalidHashError):
        pass
    if body.username != "admin" or not valid:
        raise HTTPException(401, "Credenciais inválidas")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with DB.begin() as db:
        db.add(Session(hash=digest(token), csrf=csrf, expires=time.time() + config.SESSION_SECONDS))
    response.set_cookie("session", token, secure=True, httponly=True, samesite="strict",
                        max_age=config.SESSION_SECONDS, path="/api/v1")
    return {"csrf_token": csrf}


@app.get(PREFIX + "/auth/session")
def session_info(request: Request):
    authenticate(request)
    with DB() as db:
        session = db.get(Session, digest(request.cookies.get("session", "")))
        return {"csrf_token": session.csrf if session else None}


@app.post(PREFIX + "/auth/logout")
def logout(request: Request, response: Response):
    authenticate(request)
    with DB.begin() as db:
        session = db.get(Session, digest(request.cookies.get("session", "")))
        if session:
            db.delete(session)
    response.delete_cookie("session", path="/api/v1", secure=True, httponly=True, samesite="strict")
    return {"ok": True}


def snapshot():
    with DB() as db:
        devices = db.query(Device).order_by(Device.name).all()
        states = db.query(State).all()
        ranked = select(Command.id, func.row_number().over(partition_by=Command.device_id,
                        order_by=(Command.created.desc(), Command.id.desc())).label("rank")).subquery()
        latest = {c.device_id: serialize(c)
                  for c in db.execute(select(Command).join(ranked, Command.id == ranked.c.id)
                                      .where(ranked.c.rank == 1)).scalars()}
        result = []
        for device in devices:
            interval = device.config.get("expected_interval", 300)
            values = [{"property": state.property, "value": state.value, "unit": state.unit,
                       "observed": state.observed, "received": state.received, "source": state.source,
                       "stale": time.time() - state.observed > interval * 3,
                       "observation_time_known": state.time_known and not device.config.get("cloud_snapshot_without_timestamp", False)}
                      for state in states if state.device_id == device.id]
            online = next((s for s in values if s["property"] == "online"), None)
            result.append({"id": device.id, "name": device.name,
                           "capabilities": sorted({m["property"] for m in device.config.get("properties", {}).values()}),
                           "controllable": device.config.get("command", {}).get("validated", False),
                           "control": capabilities(device),
                           "kind": device.config.get("command", {}).get("kind", "sensor"),
                           "virtual": device.config.get("virtual", False),
                           "cloud_snapshot_without_timestamp": device.config.get("cloud_snapshot_without_timestamp", False) or any(not s['observation_time_known'] for s in values if s['property'] in ('temperature','humidity')),
                           "last_command": latest.get(device.id),
                           "connectivity": "desconhecida" if not online or online["stale"] else ("online" if online["value"] else "offline"),
                           "states": values})
        return result


@app.get(PREFIX + "/devices")
def devices(request: Request):
    authenticate(request)
    return snapshot()


@app.post(PREFIX + "/devices/sync")
def sync_devices(request: Request):
    actor = authenticate(request)
    if actor != "admin":
        raise HTTPException(403, "Sincronização manual restrita ao administrador")
    if not take_rate("manual_sync", 2):
        raise HTTPException(429, "Aguarde antes de sincronizar novamente")
    from .worker import reconcile
    from .events import process_one
    reconcile(app.state.tuya)
    # Drain the inbox before returning the authoritative snapshot.
    for _ in range(1000):
        if not process_one():
            break
    with DB() as db:
        row = db.get(Health, "reconcile")
        if not row or not row.value.get("ok"):
            raise HTTPException(502, "Não foi possível atualizar todos os dispositivos na Tuya")
    return snapshot()


@app.get(PREFIX + "/devices/{device_id}/state")
def state(device_id: str, request: Request):
    authenticate(request)
    result = next((d for d in snapshot() if d["id"] == device_id), None)
    if result is None:
        raise HTTPException(404, "Dispositivo não encontrado")
    return result


@app.get(PREFIX + "/devices/{device_id}/history")
def history(device_id: str, request: Request, property: str, start: datetime, end: datetime,
            aggregation: str = Query("raw", pattern="^(raw|hour|day)$"),
            limit: int = Query(500, ge=1, le=2000), cursor_time: float | None = None,
            cursor_id: str = ""):
    authenticate(request)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "Informe o fuso horário no intervalo")
    first, last = start.timestamp(), end.timestamp()
    if first >= last or last - first > 90 * 86400:
        raise HTTPException(422, "Intervalo deve ser positivo e de até 90 dias")
    with DB() as db:
        device = db.get(Device, device_id)
        if not device:
            raise HTTPException(404, "Dispositivo não encontrado")
        time_basis = "cloud_query" if device.config.get("cloud_snapshot_without_timestamp", False) else "reported_or_received"
        query = select(Measurement).where(Measurement.device_id == device_id, Measurement.property == property,
                                           Measurement.observed >= first, Measurement.observed < last)
        if aggregation == "raw":
            if cursor_time is not None:
                query = query.where(or_(Measurement.observed > cursor_time,
                                        and_(Measurement.observed == cursor_time, Measurement.id > cursor_id)))
            rows = db.execute(query.order_by(Measurement.observed, Measurement.id).limit(limit + 1)).scalars().all()
            more = len(rows) > limit
            rows = rows[:limit]
            return {"points": [{"id": r.id, "time": r.observed, "value": r.value, "unit": r.unit} for r in rows],
                    "next_cursor": {"cursor_time": rows[-1].observed, "cursor_id": rows[-1].id} if more else None,
                    "time_basis": time_basis}
        # Max 2160 hourly buckets. Read in batches; don't materialize all raw history.
        step = 3600 if aggregation == "hour" else 86400
        buckets = {}
        for row in db.execute(query.execution_options(yield_per=1000)).scalars():
            if isinstance(row.value, bool) or not isinstance(row.value, (int, float)):
                continue
            bucket = int(row.observed // step) * step
            item = buckets.setdefault(bucket, {"sum": 0, "count": 0, "min": row.value, "max": row.value})
            item["sum"] += row.value
            item["count"] += 1
            item["min"], item["max"] = min(item["min"], row.value), max(item["max"], row.value)
        points = []
        for bucket in range(int(first // step) * step, int((last - 0.000001) // step) * step + 1, step):
            item = buckets.get(bucket)
            points.append({"time": bucket, "value": item["sum"] / item["count"] if item else None,
                           "min": item["min"] if item else None, "max": item["max"] if item else None,
                           "count": item["count"] if item else 0})
        return {"points": points, "next_cursor": None, "time_basis": time_basis}


@app.post(PREFIX + "/devices/{device_id}/commands")
def command(device_id: str, body: Power, request: Request,
            idempotency_key: str = Header(min_length=8, max_length=128)):
    actor = authenticate(request, control=True)
    if not take_rate("commands", 20):
        raise HTTPException(429, "Limite de comandos atingido")
    return submit(device_id, body.power, idempotency_key, actor, app.state.tuya)


@app.get(PREFIX + "/commands/{command_id}")
def command_status(command_id: str, request: Request):
    actor = authenticate(request)
    with DB() as db:
        row = db.get(Command, command_id)
        if not row or (actor != "admin" and row.actor != actor):
            raise HTTPException(404, "Comando não encontrado")
        return serialize(row)


def diagnostics():
    with DB() as db:
        health = {h.name: {**h.value, "updated": h.updated} for h in db.query(Health)}
        worker = health.get("worker", {})
        pulsar = health.get("pulsar", {})
        connected = pulsar.get("connected", False) and time.time() - worker.get("updated", 0) < 30
        return {"tuya_connected": connected, "health": health,
                "pending": db.query(Event).filter_by(status="pending").count(),
                "dead": db.query(Event).filter_by(status="dead").count(),
                "oldest_pending": db.scalar(select(func.min(Event.received)).where(Event.status == "pending")),
                "commands_unknown": db.query(Command).filter_by(status="resultado desconhecido").count(),
                "http_calls_window": _calls(db)}


def _calls(db):
    from .db import Rate
    rate = db.get(Rate, "tuya")
    return rate.count if rate and rate.window == int(time.time() // 60) else 0


@app.get(PREFIX + "/status")
def status(request: Request):
    authenticate(request)
    return diagnostics()


@app.get(PREFIX + "/healthz", include_in_schema=False)
def healthz():
    with DB() as db:
        db.execute(select(1))
    return {"ok": True}


@app.websocket(PREFIX + "/events")
async def events(ws: WebSocket):
    if ws.headers.get("origin") != config.ORIGIN:
        await ws.close(code=1008)
        return
    token = digest(ws.cookies.get("session", ""))
    def valid():
        with DB() as db:
            session = db.get(Session, token)
            return bool(session and session.expires > time.time())
    if not await asyncio.to_thread(valid):
        await ws.close(code=1008)
        return
    await ws.accept()
    previous = ""
    try:
        while await asyncio.to_thread(valid):
            value = await asyncio.to_thread(snapshot)
            signature = json.dumps(value, sort_keys=True)
            if signature != previous:
                await ws.send_json({"type": "snapshot", "devices": value})
                previous = signature
            else:
                await ws.send_json({"type": "heartbeat"})
            await asyncio.sleep(2)
        await ws.close(code=1008)
    except (WebSocketDisconnect, RuntimeError):
        pass
