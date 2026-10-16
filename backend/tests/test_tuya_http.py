import time
from unittest.mock import Mock
import pytest
import httpx
from app.tuya import TuyaHTTP, Rejected
from app.db import Device


def response(result=None,code=None,status=200):
    return httpx.Response(status,request=httpx.Request("GET","https://example.test"),json={"success":code is None,"result":result,"code":code})


def test_expired_token_refresh_and_read_retry():
    api=TuyaHTTP()
    api.client=Mock()
    api.client.request.side_effect=[response({"access_token":"one","expire_time":3600}),response(code=1010),response({"access_token":"two","expire_time":3600}),response({"ok":True})]
    assert api.request("GET","/v1.0/devices/sensor")=={"ok":True}
    assert api.token=="two"


def test_command_not_retried_on_expired_token():
    api=TuyaHTTP();api.token="one";api.expiry=time.time()+1000;api.client=Mock()
    api.client.request.return_value=response(code=1010)
    with pytest.raises(Rejected):api.request("POST","/v1.0/devices/sensor/commands",{})
    assert api.client.request.call_count==1


def test_rate_limit_not_retried():
    api=TuyaHTTP();api.token="one";api.expiry=time.time()+1000;api.client=Mock()
    api.client.request.return_value=response(status=429)
    with pytest.raises(Rejected,match="rate_limit"):api.request("POST","/commands",{})
    assert api.client.request.call_count==1


def test_service_failure_not_retried():
    api=TuyaHTTP();api.token="one";api.expiry=time.time()+1000;api.client=Mock()
    api.client.request.return_value=response(status=503)
    with pytest.raises(httpx.HTTPStatusError):api.request("POST","/commands",{})
    assert api.client.request.call_count==1


def test_iot03_status_route():
    api=TuyaHTTP()
    api.request=Mock(return_value=[{"code":"va_temperature","value":-200}])
    device=Device(id="virtual-sensor",name="Virtual",config={"api_family":"iot-03"})
    assert api.read_status(device)=={"status":[{"code":"va_temperature","value":-200}]}
    api.request.assert_called_once_with("GET","/v1.0/iot-03/devices/virtual-sensor/status")


def test_legacy_status_route():
    api=TuyaHTTP()
    api.request=Mock(return_value={"online":True,"status":[]})
    device=Device(id="sensor",name="Sensor",config={})
    assert api.read_status(device)["online"] is True
    api.request.assert_called_once_with("GET","/v1.0/devices/sensor")


def test_client_credential_aliases(monkeypatch):
    from app import config
    for name in ("TUYA_ACCESS_ID","TUYA_ACCESS_SECRET","TUYA_ACCESS_ID_FILE","TUYA_ACCESS_SECRET_FILE"):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv("TUYA_CLIENT_ID","alias-id")
    monkeypatch.setenv("TUYA_CLIENT_SECRET","alias-secret")
    assert config.tuya_access_id()=="alias-id"
    assert config.tuya_access_secret()=="alias-secret"
