import time
from unittest.mock import Mock
import pytest
from app.db import DB, Device, ApiKey, State
from app.main import app
from app.security import digest
from app.tuya import TuyaHTTP
from app.worker import reconcile
from app.events import process_one


def setup(**kwargs):
    return {'id':'combined','name':'Sensor e IR','sensing':True,'infrared':True,'hub_id':'hub_1','remote_id':'remote_1',**kwargs}


def test_register_combined_or_separate_and_block_unvalidated_commands(logged):
    saved=logged.put('/api/v1/integrations/devices',json=setup())
    assert saved.status_code==200 and not saved.json()['control']['power']
    rows=logged.get('/api/v1/devices').json()
    combined=next(d for d in rows if d['id']=='combined')
    assert 'temperature' in combined['capabilities'] and combined['kind']=='ir'
    assert logged.post('/api/v1/devices/combined/control/commands',json={'type':'power','value':True},headers={'Idempotency-Key':'blocked-key'}).status_code==422
    assert logged.put('/api/v1/integrations/devices',json=setup(id='only_ir',sensing=False)).status_code==200
    assert logged.put('/api/v1/integrations/devices',json=setup(id='only_sensor',infrared=False)).status_code==200


def test_command_temperature_range_and_idempotency(logged):
    logged.put('/api/v1/integrations/devices',json=setup(power_enabled=True,temperature_enabled=True))
    adapter=Mock();adapter.control.return_value=True;app.state.tuya=adapter
    url='/api/v1/devices/combined/control/commands';headers={'Idempotency-Key':'ac-temperature-22'}
    assert logged.post(url,json={'type':'temperature','value':22},headers=headers).status_code==200
    assert logged.post(url,json={'type':'temperature','value':22},headers=headers).status_code==200
    assert adapter.control.call_count==1
    assert logged.post(url,json={'type':'temperature','value':35},headers={'Idempotency-Key':'outside-range'}).status_code==422
    assert logged.post(url,json={'type':'power','value':1},headers={'Idempotency-Key':'invalid-bool'}).status_code==422
    state=logged.get('/api/v1/devices/combined/control').json()
    assert state['states'][0]['property']=='target_temperature'
    assert state['states'][0]['source']=='estimado' and state['states'][0]['value']==22


def test_status_from_tuya_is_always_estimated(logged):
    logged.put('/api/v1/integrations/devices',json=setup(status_enabled=True))
    adapter=Mock();adapter.read_control.return_value={'power':'1','temp':'24','mode':'0','wind':'1'};app.state.tuya=adapter
    result=logged.post('/api/v1/devices/combined/control/status')
    assert result.status_code==200
    assert all(s['source']=='estimado' for s in result.json()['states'])
    assert next(s['value'] for s in result.json()['states'] if s['property']=='target_temperature')==24


def test_combined_device_is_still_reconciled_as_sensor(logged):
    logged.put('/api/v1/integrations/devices',json=setup())
    adapter=Mock();adapter.read_status.return_value={'status':[{'code':'va_temperature','value':280}]}
    reconcile(adapter)
    assert any(call.args[0].id=='combined' for call in adapter.read_status.call_args_list)
    while process_one():pass
    with DB() as db:
        state=db.get(State,('combined','temperature'))
        assert state.value==28 and not state.time_known


def test_exact_v2_ir_routes_and_payload(logged):
    logged.put('/api/v1/integrations/devices',json=setup(power_enabled=True,temperature_enabled=True))
    with DB() as db:device=db.get(Device,'combined')
    api=TuyaHTTP();api.request=Mock(return_value=True)
    api.command(device,True)
    api.request.assert_called_with('POST','/v2.0/infrareds/hub_1/air-conditioners/remote_1/command',{'code':'power','value':1})
    api.control(device,{'type':'temperature','value':23})
    api.request.assert_called_with('POST','/v2.0/infrareds/hub_1/air-conditioners/remote_1/command',{'code':'temp','value':23})
    api.read_control(device)
    api.request.assert_called_with('GET','/v2.0/infrareds/hub_1/remotes/remote_1/ac/status')
    api.client.close()


def test_ids_and_role_capabilities_are_validated(logged):
    assert logged.put('/api/v1/integrations/devices',json=setup(id='../bad')).status_code==422
    assert logged.put('/api/v1/integrations/devices',json=setup(remote_id='',power_enabled=True)).status_code==422
    assert logged.put('/api/v1/integrations/devices',json=setup(sensing=False,infrared=False)).status_code==422
    assert logged.put('/api/v1/integrations/devices',json=setup(hub_id='x/../../escape')).status_code==422


def test_registry_changes_require_admin_and_csrf(logged,client):
    assert logged.put('/api/v1/integrations/devices',json=setup(),headers={'X-CSRF-Token':'bad'}).status_code==403
    with DB.begin() as db:db.add(ApiKey(hash=digest('readonly-registry'),name='reader',control=False))
    assert client.put('/api/v1/integrations/devices',json=setup(),headers={'Authorization':'Bearer readonly-registry'}).status_code==403
    assert client.post('/api/v1/devices/remote/control/commands',json={'type':'power','value':True},headers={'Authorization':'Bearer readonly-registry','Idempotency-Key':'no-key-control'}).status_code==403


def test_changing_remote_clears_previous_estimated_state(logged):
    logged.put('/api/v1/integrations/devices',json=setup())
    with DB.begin() as db:
        db.add(State(device_id='combined',property='target_temperature',value=22,unit='°C',source='estimado',observed=time.time(),received=time.time()))
    assert logged.put('/api/v1/integrations/devices',json=setup(remote_id='new_remote')).status_code==200
    assert logged.get('/api/v1/devices/combined/control').json()['states']==[]


def test_standard_ir_keys_are_discovered_whitelisted_and_audited(logged):
    body=setup(profile='tuya_standard_ir',keys_enabled=True)
    assert logged.put('/api/v1/integrations/devices',json=body).status_code==200
    adapter=Mock();app.state.tuya=adapter
    adapter.read_keys.return_value={'category_id':2,'remote_index':123,'duplicate_power':True,'key_list':[
        {'key':'Power','key_name':'On/Off','standard_key':True},
        {'key':'Volume-','key_name':'Volume Down','standard_key':True},
        {'key':'unsafe-custom','standard_key':False}]}
    discovered=logged.post('/api/v1/devices/combined/control/discover')
    assert discovered.status_code==200
    caps=discovered.json()['capabilities']
    assert len(caps['keys'])==2 and not caps['power'] and caps['temperature'] is None and not caps['cloud_status']
    adapter.control.return_value=True
    url='/api/v1/devices/combined/control/commands'
    result=logged.post(url,json={'type':'ir_key','value':'Volume-'},headers={'Idempotency-Key':'tv-key-test-001'})
    assert result.status_code==200 and result.json()['status']=='aceito pela Tuya'
    logged.post(url,json={'type':'ir_key','value':'Volume-'},headers={'Idempotency-Key':'tv-key-test-001'})
    assert adapter.control.call_count==1
    assert logged.post(url,json={'type':'ir_key','value':'unsafe-custom'},headers={'Idempotency-Key':'reject-custom'}).status_code==422
    assert logged.post(url,json={'type':'power','value':True},headers={'Idempotency-Key':'reject-discrete-power'}).status_code==422
    with DB() as db:
        assert db.get(State,('combined','power')) is None
        assert db.get(State,('combined','last_ir_key')).value=='Volume-'
        device=db.get(Device,'combined')
    api=TuyaHTTP();api.request=Mock(return_value=True)
    api.control(device,{'type':'ir_key','value':'Volume-'})
    api.request.assert_called_once_with('POST','/v2.0/infrareds/hub_1/remotes/remote_1/command',{'categoryId':2,'remoteIndex':123,'key':'Volume-'})
    api.client.close()


def test_remote_change_invalidates_discovered_keys(logged):
    logged.put('/api/v1/integrations/devices',json=setup(profile='tuya_standard_ir',keys_enabled=True))
    adapter=Mock();app.state.tuya=adapter
    adapter.read_keys.return_value={'category_id':2,'remote_index':123,'key_list':[{'key':'Power','standard_key':True}]}
    assert logged.post('/api/v1/devices/combined/control/discover').status_code==200
    assert logged.put('/api/v1/integrations/devices',json=setup(profile='tuya_standard_ir',keys_enabled=True,remote_id='new_tv')).status_code==200
    assert logged.get('/api/v1/devices/combined/control').json()['capabilities']['keys']==[]
    assert logged.put('/api/v1/integrations/devices',json=setup(profile='tuya_standard_ir',power_enabled=True)).status_code==422
