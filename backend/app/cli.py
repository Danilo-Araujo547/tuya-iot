import argparse
import getpass
import json
import re
import secrets
import time
from pathlib import Path
from argon2 import PasswordHasher
from sqlalchemy import text
from . import config
from .db import Base, DB, engine, Device, ApiKey, Rate, Event, Appearance
from .security import digest
from .tuya import TuyaHTTP


def migrate():
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    else:
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(42916701)"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)"))
            for version, filename in [('001', '001_initial.sql'), ('002', '002_appearance.sql'), ('003', '003_automations.sql')]:
                if not conn.execute(text("SELECT 1 FROM schema_migrations WHERE version=:version"), {'version': version}).first():
                    sql = (Path(__file__).parent.parent / 'migrations' / filename).read_text()
                    for statement in sql.split(';'):
                        if statement.strip():
                            conn.execute(text(statement))
                    conn.execute(text("INSERT INTO schema_migrations VALUES (:version)"), {'version': version})
    with DB.begin() as db:
        if not db.get(Appearance, 'dashboard'):
            db.add(Appearance(id='dashboard', selected='solar'))
        for key in ("tuya", "login", "commands", "manual_sync"):
            if not db.get(Rate, key):
                db.add(Rate(key=key, window=0, count=0))


def load_devices(path):
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) > 50:
        raise ValueError("Configure uma lista de até 50 dispositivos")
    seen = set()
    for row in entries:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", row["id"]) or row["id"] in seen:
            raise ValueError("Identificador inválido ou duplicado")
        seen.add(row["id"])
        if row.get("api_family", "legacy") not in ("legacy", "iot-03"):
            raise ValueError("Família de API inválida")
        if not row.get("name") or not 1 <= row.get("expected_interval", 300) <= 86400:
            raise ValueError("Nome ou intervalo inválido")
        for mapping in row.get("properties", {}).values():
            if mapping["property"] not in ("temperature", "humidity", "power", "online"):
                raise ValueError("Propriedade não suportada")
            if not 0 <= mapping.get("scale", 0) <= 6:
                raise ValueError("Escala inválida")
            if mapping.get("type", "number") not in ("number", "boolean"):
                raise ValueError("Tipo inválido")
        command = row.get("command", {})
        if command:
            if command.get("kind") not in ("device", "ir"):
                raise ValueError("Adaptador inválido")
            if command["kind"] == "ir":
                if command.get('profile') in ('tuya_ac_v2','tuya_standard_ir'):
                    for key in ('infrared_id', 'remote_id'):
                        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', command.get(key, '')):
                            raise ValueError('Informe os IDs do hub e controle virtual')
                    ac = command.get('ac', {})
                    bounds = ac.get('temperature', {})
                    if command.get('profile')=='tuya_ac_v2' and ac.get('validated') and not (type(bounds.get('min')) is int and type(bounds.get('max')) is int and 10 <= bounds['min'] < bounds['max'] <= 35):
                        raise ValueError('Informe os limites de temperatura validados')
                    if command.get('profile')=='tuya_standard_ir' and command.get('keys_validated'):
                        if type(command.get('category_id')) is not int or type(command.get('remote_index')) is not int or not isinstance(command.get('keys'),list):
                            raise ValueError('Informe os metadados de teclas consultados na Tuya')
                else:
                    if not re.fullmatch(r"/v[12]\.0/infrareds/[A-Za-z0-9_/-]+", command.get("path", "")):
                        raise ValueError("Caminho IR inválido")
                    if not isinstance(command.get("on"), dict) or not isinstance(command.get("off"), dict):
                        raise ValueError("Informe os corpos IR on/off validados")
            elif not command.get("code"):
                raise ValueError("Informe o código de comando")
    with DB.begin() as db:
        for row in entries:
            prior = db.get(Device, row['id'])
            if prior and prior.config.get('managed_by_ui'):
                continue
            db.merge(Device(id=row["id"], name=row["name"], config=row))
    return len(entries)


def main():
    parser = argparse.ArgumentParser(description="Operação Tuya IoT")
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("migrate")
    subs.add_parser("hash-password")
    provision = subs.add_parser("provision")
    provision.add_argument("--file", default=config.CONFIG_PATH)
    key = subs.add_parser("create-key")
    key.add_argument("--name", required=True)
    key.add_argument("--control", action="store_true")
    revoke = subs.add_parser("revoke-key")
    revoke.add_argument("--name", required=True)
    retry = subs.add_parser("replay")
    retry.add_argument("--event", required=True)
    subs.add_parser("dead-events")
    probe = subs.add_parser("probe")
    probe.add_argument("--device", required=True)
    probe.add_argument("--infrared", action="store_true")
    probe.add_argument("--api-family", choices=["iot-03", "legacy"], default="iot-03")
    discover = subs.add_parser("discover")
    discover.add_argument("--uid", required=True, help="UID da conta Smart Life vinculada ao projeto")
    args = parser.parse_args()
    if args.action == "migrate":
        migrate()
    elif args.action == "hash-password":
        password = getpass.getpass("Senha administrativa (mínimo 14 caracteres): ")
        if len(password) < 14:
            raise ValueError("Senha curta")
        print(PasswordHasher().hash(password))
    elif args.action == "provision":
        print(json.dumps({"provisioned": load_devices(args.file)}))
    elif args.action == "create-key":
        value = secrets.token_urlsafe(32)
        with DB.begin() as db:
            db.add(ApiKey(hash=digest(value), name=args.name, control=args.control))
        print(value)  # Deliberately shown exactly once to the operator.
    elif args.action == "revoke-key":
        with DB.begin() as db:
            db.query(ApiKey).filter_by(name=args.name).delete()
    elif args.action == "replay":
        with DB.begin() as db:
            row = db.get(Event, args.event)
            if not row or row.status != "dead":
                raise ValueError("Evento não está na fila de falhas")
            row.status, row.attempts, row.next_attempt, row.error = "pending", 0, 0, None
    elif args.action == "dead-events":
        with DB() as db:
            print(json.dumps([{"id": e.id, "attempts": e.attempts, "error": e.error}
                              for e in db.query(Event).filter_by(status="dead").limit(100)]))
    elif args.action == "discover":
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.uid):
            raise ValueError("UID inválido")
        print(json.dumps(TuyaHTTP().request("GET", f"/v1.0/users/{args.uid}/devices"), ensure_ascii=False, indent=2))
    elif args.action == "probe":
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.device):
            raise ValueError("Identificador inválido")
        api = TuyaHTTP()
        if args.infrared:
            result = api.request("GET", f"/v2.0/infrareds/{args.device}/remotes")
        elif args.api_family == "iot-03":
            result = {"status": api.request("GET", f"/v1.0/iot-03/devices/{args.device}/status"),
                      "specification": api.request("GET", f"/v1.0/iot-03/devices/{args.device}/specification")}
        else:
            result = {"device": api.request("GET", f"/v1.0/devices/{args.device}"),
                      "specification": api.request("GET", f"/v1.0/devices/{args.device}/specifications")}
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
