import hashlib
import hmac
import secrets
import time
from fastapi import HTTPException, Request
from .config import ORIGIN
from .db import DB, Session, ApiKey


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate(request: Request, control=False):
    token = request.headers.get("authorization", "")
    with DB() as db:
        if token.startswith("Bearer "):
            key = db.get(ApiKey, digest(token[7:]))
            if not key:
                raise HTTPException(401, "Chave inválida")
            if control and not key.control:
                raise HTTPException(403, "Sem permissão de controle")
            return "key:" + key.name
        session = db.get(Session, digest(request.cookies.get("session", "")))
        if not session or session.expires <= time.time():
            raise HTTPException(401, "Sessão expirada")
        if request.method not in ("GET", "HEAD"):
            if request.headers.get("origin") != ORIGIN or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf):
                raise HTTPException(403, "CSRF inválido")
        return "admin"
