import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["APP_ORIGIN"] = "https://testserver"
os.environ["TUYA_ACCESS_ID"] = "test-id"
os.environ["TUYA_ACCESS_SECRET"] = "0123456789abcdef0123456789abcdef"
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from app import db
from app.db import Base, Device, Rate, Appearance


@pytest.fixture(autouse=True)
def database():
    # Set TEST_POSTGRES_URL for the real PostgreSQL integration suite.
    url = os.getenv("TEST_POSTGRES_URL", "sqlite://")
    engine = create_engine(url, **({"connect_args": {"check_same_thread": False}, "poolclass": StaticPool} if url.startswith("sqlite") else {}))
    db.DB.configure(bind=engine)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with db.DB.begin() as session:
        session.add(Appearance(id='dashboard', selected='solar'))
        for name in ("tuya", "login", "commands", "manual_sync"):
            session.add(Rate(key=name, window=0, count=0))
        session.add(Device(id="sensor", name="Sala", config={"properties": {
            "temp_current": {"property": "temperature", "scale": 1, "unit": "°C"},
            "humidity_value": {"property": "humidity", "scale": 0, "unit": "%"}}, "expected_interval": 300}))
        session.add(Device(id="remote", name="Ar", config={"command": {"kind": "ir", "validated": True}, "properties": {}}))
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    os.environ["ADMIN_PASSWORD_HASH"] = PasswordHasher().hash("correct-password-123")
    from app.main import app
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def logged(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-password-123"}, headers={"Origin": "https://testserver"})
    assert response.status_code == 200
    client.headers.update({"Origin": "https://testserver", "X-CSRF-Token": response.json()["csrf_token"]})
    return client
