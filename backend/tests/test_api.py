import time
from datetime import datetime, timezone
from unittest.mock import Mock
import httpx
import pytest
from app.db import DB, ApiKey, Session, Device, State, Command, Event
from app.security import digest
from app.events import ingest, process_one
from app.commands import submit
from app.tuya import Rejected


def test_unauthenticated_and_wrong_login(client):
    assert client.get("/api/v1/devices").status_code == 401
    assert client.post("/api/v1/auth/login", headers={"Origin": "https://testserver"}, json={"username":"admin", "password":"wrong"}).status_code == 401


def test_cookie_csrf_logout(logged):
    assert logged.get("/api/v1/devices").status_code == 200
    assert logged.post("/api/v1/auth/logout", headers={"X-CSRF-Token":"bad"}).status_code == 403
    assert logged.post("/api/v1/auth/logout").status_code == 200
    assert logged.get("/api/v1/devices").status_code == 401


def test_secure_cookie_flags(client):
    r=client.post("/api/v1/auth/login", headers={"Origin":"https://testserver"},json={"username":"admin","password":"correct-password-123"})
    cookie=r.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("httponly", "secure", "samesite=strict"))


def test_expired_session(logged):
    with DB.begin() as db:
        for session in db.query(Session): session.expires = 0
    assert logged.get("/api/v1/devices").status_code == 401


def test_readonly_key_cannot_control(client):
    with DB.begin() as db:
        db.add(ApiKey(hash=digest("readonly"), name="zabbix", control=False))
    headers={"Authorization":"Bearer readonly", "Idempotency-Key":"unique-key"}
    assert client.get("/api/v1/devices", headers=headers).status_code == 200
    assert client.post("/api/v1/devices/remote/commands", headers=headers,json={"power":True}).status_code == 403
    assert client.get("/api/v1/status",headers={"Authorization":"Bearer invalid"}).status_code == 401


@pytest.mark.parametrize("outcome,status", [(None,"aceito pela Tuya"),(Rejected("denied"),"falhou"),(httpx.ReadTimeout("timeout"),"resultado desconhecido")])
def test_command_audit_and_idempotency(outcome,status):
    adapter=Mock()
    adapter.command.return_value=True
    if outcome: adapter.command.side_effect=outcome
    result=submit("remote", True, "same-key", "admin", adapter)
    assert result["status"]==status
    assert submit("remote", True, "same-key", "admin", adapter)["id"]==result["id"]
    adapter.command.assert_called_once()
    with DB() as db:
        state=db.get(State,("remote","power"))
        if outcome is None: assert state.source=="estimado"
        else: assert state is None


def test_idempotency_conflict(logged):
    from app.main import app
    app.state.tuya=Mock()
    app.state.tuya.command.return_value=True
    headers={"Idempotency-Key":"test-key-123"}
    assert logged.post("/api/v1/devices/remote/commands",json={"power":True},headers=headers).status_code==200
    assert logged.post("/api/v1/devices/remote/commands",json={"power":False},headers=headers).status_code==409
    assert logged.post("/api/v1/devices/sensor/commands",json={"power":True},headers={"Idempotency-Key":"different-key"}).status_code==422
    state=logged.get("/api/v1/devices/remote/state").json()
    assert state["last_command"]["power"] is True
    assert state["last_command"]["status"]=="aceito pela Tuya"


def test_false_result_does_not_mark_accepted():
    adapter=Mock();adapter.command.return_value=False
    result=submit("remote",True,"false-result","admin",adapter)
    assert result["status"]=="falhou"
    with DB() as db:
        assert db.get(State,("remote","power")) is None


def test_snapshot_staleness(logged):
    with DB.begin() as db:
        db.add(State(device_id="sensor", property="temperature", value=25,unit="°C",observed=time.time()-1000,received=time.time(),source="reportado"))
    result=logged.get("/api/v1/devices/sensor/state").json()
    assert result["states"][0]["stale"] is True
    assert result["connectivity"]=="desconhecida"


def test_cloud_query_time_is_not_claimed_as_measurement_time(logged):
    with DB.begin() as db:
        device=db.get(Device,"sensor")
        device.config={**device.config,"cloud_snapshot_without_timestamp":True,"virtual":True}
        db.add(State(device_id="sensor",property="temperature",value=-20,unit="°C",observed=time.time(),received=time.time(),source="reportado"))
    result=logged.get("/api/v1/devices/sensor/state").json()
    assert result["virtual"] is True
    assert result["states"][0]["observation_time_known"] is False


def test_manual_refresh_queries_tuya_and_returns_new_state(logged):
    from app.main import app
    adapter=Mock()
    adapter.read_status.return_value={"status":[{"code":"temp_current","value":110}]}
    app.state.tuya=adapter
    ingest({"devId":"sensor","status":[{"code":"temp_current","value":-200}]},"before-sync")
    process_one()
    assert logged.get("/api/v1/devices/sensor/state").json()["states"][0]["value"]==-20
    response=logged.post("/api/v1/devices/sync")
    assert response.status_code==200
    sensor=next(d for d in response.json() if d["id"]=="sensor")
    assert sensor["states"][0]["value"]==11
    adapter.read_status.assert_called_once()


def test_readonly_key_cannot_trigger_cloud_sync(client):
    with DB.begin() as db:
        db.add(ApiKey(hash=digest("readonly-sync"),name="sync-viewer",control=False))
    assert client.post("/api/v1/devices/sync",headers={"Authorization":"Bearer readonly-sync"}).status_code==403


def test_history_gaps_and_raw_pagination(logged):
    now=int(time.time()//3600)*3600
    for i in (0,2):
        ingest({"devId":"sensor","ts":int((now-i*3600)*1000),"status":[{"code":"temp_current","value":250}]},str(i));process_one()
    params={"property":"temperature","start":datetime.fromtimestamp(now-7200,timezone.utc).isoformat(),"end":datetime.fromtimestamp(now+1,timezone.utc).isoformat(),"aggregation":"hour"}
    result=logged.get("/api/v1/devices/sensor/history",params=params)
    assert result.status_code==200
    assert [p["value"] for p in result.json()["points"]]==[25,None,25]
    params.update(aggregation="raw",limit=1)
    page=logged.get("/api/v1/devices/sensor/history",params=params).json()
    assert page["next_cursor"]
    params.update(page["next_cursor"])
    other=logged.get("/api/v1/devices/sensor/history",params=params).json()
    assert other["points"][0]["id"]!=page["points"][0]["id"]


def test_websocket_snapshot_reconnect_and_origin(logged):
    for _ in range(2):
        with logged.websocket_connect("wss://testserver/api/v1/events",headers={"Origin":"https://testserver"}) as ws:
            assert ws.receive_json()["type"]=="snapshot"
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with logged.websocket_connect("wss://testserver/api/v1/events",headers={"Origin":"https://evil.example"}): pass


def test_dead_replay_and_interrupted_command():
    from app.worker import maintenance
    with DB.begin() as db:
        db.add(Command(device_id="remote",actor="admin",key="interrupt",power=True,created=time.time()-120))
    maintenance()
    with DB() as db:
        assert db.query(Command).one().status=="resultado desconhecido"
