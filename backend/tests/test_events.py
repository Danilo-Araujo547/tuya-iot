import time
import json
import base64
import threading
from unittest.mock import Mock, patch
import pytest
from Crypto.Cipher import AES
from app.db import DB, Event, State, Measurement
from app.events import ingest, process_one
from app.tuya import DurablePulsar


def payload(value=245, ts=None):
    return {"devId": "sensor", "ts": int((ts or time.time()) * 1000), "status": [{"code": "temp_current", "value": value}]}


def test_normalization_deduplication_and_restart(database):
    ingest(payload(), "message-1")
    database.dispose() if database.dialect.name != "sqlite" else None
    ingest(payload(), "message-1")
    assert process_one()
    assert not process_one()
    with DB() as db:
        assert db.query(Measurement).count() == 1
        assert db.get(State, ("sensor", "temperature")).value == 24.5


def test_out_of_order_keeps_history_without_rewinding_state():
    now = time.time()
    ingest(payload(260, now), "new")
    process_one()
    ingest(payload(230, now - 300), "old")
    process_one()
    with DB() as db:
        assert db.query(Measurement).count() == 2
        assert db.get(State, ("sensor", "temperature")).value == 26


def test_virtual_sensor_actual_codes_and_scales():
    from app.cli import load_devices
    from pathlib import Path
    config=Path(__file__).resolve().parents[2]/"config/sensor-virtual.validated.json"
    load_devices(config)
    ingest({"devId":"vdevo179208885319728","status":[
        {"code":"va_temperature","value":-200},{"code":"va_humidity","value":0}]},"virtual-status")
    process_one()
    with DB() as db:
        assert db.get(State,("vdevo179208885319728","temperature")).value == -20
        assert db.get(State,("vdevo179208885319728","humidity")).value == 0


def test_stable_fallback_hash():
    data = payload()
    assert ingest(data) == ingest(dict(reversed(list(data.items()))))
    with DB() as db:
        assert db.query(Event).count() == 1


def test_invalid_partial_event_rolls_back_and_dead_letters():
    data = payload()
    data["status"].append({"code": "humidity_value", "value": "broken"})
    ingest(data, "bad")
    for attempt in range(5):
        with DB.begin() as db:
            db.get(Event, "bad").next_attempt = 0
        process_one()
    with DB() as db:
        assert db.get(Event, "bad").status == "dead"
        assert db.get(Event, "bad").attempts == 5
        assert db.query(Measurement).count() == 0
        assert db.query(State).count() == 0


@pytest.mark.parametrize("value", [True, "NaN", "Infinity"])
def test_invalid_numeric_values(value):
    ingest(payload(value), "invalid")
    process_one()
    with DB() as db:
        assert db.query(Measurement).count() == 0


def test_offline_event():
    ingest({"bizCode": "offline", "bizData": {"devId": "sensor"}, "ts": int(time.time()*1000)}, "offline")
    process_one()
    with DB() as db:
        assert db.get(State, ("sensor", "online")).value is False


def envelope():
    raw = json.dumps(payload()).encode()
    padding = 16-len(raw)%16
    encrypted = AES.new(b"89abcdef01234567", AES.MODE_ECB).encrypt(raw + bytes([padding])*padding)
    wrapped = json.dumps({"data": base64.b64encode(encrypted).decode()}).encode()
    return json.dumps({"messageId": "broker-1", "payload": base64.b64encode(wrapped).decode()})


def test_pulsar_ack_after_commit():
    consumer = DurablePulsar(threading.Event())
    ws = Mock()
    def ack(_):
        with DB() as db:
            assert db.get(Event, "pulsar:broker-1") is not None
    ws.send.side_effect = ack
    consumer._on_message(ws, envelope())
    ws.send.assert_called_once()
    ws.close.assert_not_called()


def test_pulsar_no_ack_on_storage_failure():
    consumer = DurablePulsar(threading.Event())
    ws = Mock()
    with patch("app.tuya.ingest", side_effect=RuntimeError("db down")):
        consumer._on_message(ws, envelope())
    ws.send.assert_not_called()
    ws.close.assert_called_once()


def test_tls_and_reconnect_request():
    consumer = DurablePulsar(threading.Event())
    consumer.on_open(None)
    assert consumer.reconcile.is_set()
    consumer.ws_app = Mock()
    consumer.ws_app.run_forever.side_effect = lambda **kw: consumer._stop_event.set()
    consumer.run()
    import ssl
    assert consumer.ws_app.run_forever.call_args.kwargs["sslopt"]["cert_reqs"] == ssl.CERT_REQUIRED
