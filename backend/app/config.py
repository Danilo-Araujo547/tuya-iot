import os
from pathlib import Path


def secret(name: str, default: str = "") -> str:
    path = os.getenv(name + "_FILE")
    return Path(path).read_text().strip() if path else os.getenv(name, default)


def tuya_access_id():
    return secret("TUYA_ACCESS_ID") or secret("TUYA_CLIENT_ID")


def tuya_access_secret():
    return secret("TUYA_ACCESS_SECRET") or secret("TUYA_CLIENT_SECRET")


DATABASE_URL = secret("DATABASE_URL", "sqlite:///./local.db")
ORIGIN = os.getenv("APP_ORIGIN", "https://localhost")
CONFIG_PATH = os.getenv("DEVICE_CONFIG", "/config/devices.json")
SESSION_SECONDS = 8 * 3600
TUYA_ENDPOINT = os.getenv("TUYA_ENDPOINT", "https://openapi.tuyaus.com")
PULSAR_ENDPOINT = os.getenv("TUYA_PULSAR_ENDPOINT", "wss://mqe.tuyaus.com:8285/")
CALLS_PER_MINUTE = int(os.getenv("TUYA_CALLS_PER_MINUTE", "30"))
RECONCILE_SECONDS = max(60, int(os.getenv("TUYA_RECONCILE_SECONDS", "3600")))
