import time
from unittest.mock import Mock
from app.db import DB, State, Measurement, Device
from app.worker import reconcile
from app.events import process_one


def test_offline_cached_temperature_is_not_current(logged):
    now=time.time()
    with DB.begin() as db:
        db.add(State(device_id='sensor',property='temperature',value=21.6,unit='C',observed=now,received=now,time_known=False))
        db.add(State(device_id='sensor',property='online',value=False,unit='',observed=now,received=now))
    data=logged.get('/api/v1/devices/sensor/state').json()
    assert data['online'] is False and data['connectivity']=='offline'
    value=next(s for s in data['states'] if s['property']=='temperature')
    assert value['value']==21.6 and value['stale'] is True and value['current'] is False
    assert value['measurement_at'] is None and value['freshness_reason']=='sensor_offline'
    status=logged.get('/api/v1/devices/sensor/connectivity')
    assert status.status_code==200 and status.json()['online'] is False
    assert status.json()['connectivity_checked_at']==now


def test_offline_reconcile_does_not_add_cached_measurements(logged):
    now=time.time()-100
    with DB.begin() as db:
        db.add(State(device_id='sensor',property='temperature',value=21.6,unit='C',observed=now,received=now))
    adapter=Mock()
    adapter.read_status.return_value={'online':False,'status':[{'code':'temp_current','value':216}]}
    reconcile(adapter)
    while process_one():pass
    with DB() as db:
        assert db.get(State,('sensor','temperature')).observed==now
        assert db.query(Measurement).filter_by(property='temperature').count()==0
    assert logged.get('/api/v1/devices/sensor/connectivity').json()['online'] is False


def test_stale_connection_is_unknown_and_api_requires_auth(client,logged):
    with DB.begin() as db:
        db.add(State(device_id='sensor',property='online',value=False,unit='',observed=time.time()-1000,received=time.time()-1000))
    result=logged.get('/api/v1/devices/sensor/connectivity').json()
    assert result['online'] is None and result['connectivity']=='desconhecida'
    assert logged.get('/api/v1/devices/missing/connectivity').status_code==404
    logged.cookies.clear()
    assert client.get('/api/v1/devices/sensor/connectivity').status_code==401


def test_unknown_measurement_time_is_not_fresh_even_when_online(logged):
    now=time.time()
    with DB.begin() as db:
        db.add(State(device_id='sensor',property='temperature',value=22,unit='C',observed=now,received=now,time_known=False))
        db.add(State(device_id='sensor',property='online',value=True,unit='',observed=now,received=now))
    data=logged.get('/api/v1/devices/sensor/state').json()
    value=next(s for s in data['states'] if s['property']=='temperature')
    assert data['online'] is True
    assert value['stale'] and not value['current'] and value['measurement_at'] is None
    assert value['freshness_reason']=='measurement_time_unknown'
