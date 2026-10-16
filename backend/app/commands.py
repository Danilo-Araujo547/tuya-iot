import time
import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from .db import DB, Device, Command, State
from .tuya import Rejected


def serialize(command):
    return {key: getattr(command, key) for key in ("id", "device_id", "power", "status", "response", "created", "updated")}


def submit(device_id, power, key, actor, adapter):
    with DB() as db:
        prior = db.query(Command).filter_by(actor=actor, key=key).first()
        if prior:
            if prior.device_id != device_id or prior.power != power:
                raise HTTPException(409, "Chave de idempotência usada para outro comando")
            return serialize(prior)
        device = db.get(Device, device_id)
        if not device:
            raise HTTPException(404, "Dispositivo não encontrado")
        if not device.config.get("command", {}).get("validated", False):
            raise HTTPException(422, "Controle não validado para este aparelho")
        command = Command(device_id=device_id, actor=actor, key=key, power=power)
        db.add(command)
        try:
            db.commit()  # Durable audit BEFORE calling an external system.
        except IntegrityError:
            db.rollback()
            return submit(device_id, power, key, actor, adapter)
        command_id = command.id
    status, result = "aceito pela Tuya", None
    try:
        accepted = adapter.command(device, power)
        if accepted is False:
            raise Rejected("command_not_accepted")
        result = {"result": accepted}
    except Rejected as exc:
        status, result = "falhou", {"code": exc.code}
    except Exception as exc:
        # Never retry: even a connection failure can have an ambiguous outcome.
        status, result = "resultado desconhecido", {"error": type(exc).__name__}
    with DB.begin() as db:
        command = db.get(Command, command_id)
        command.status, command.response, command.updated = status, result, time.time()
        if status == "aceito pela Tuya":
            # Cloud acceptance is an estimate, including Wi-Fi commands until report.
            state = db.get(State, (device_id, "power"))
            if not state or state.observed <= command.created:
                db.merge(State(device_id=device_id, property="power", value=power, unit="",
                               observed=command.created, received=time.time(), source="estimado"))
        return serialize(command)
