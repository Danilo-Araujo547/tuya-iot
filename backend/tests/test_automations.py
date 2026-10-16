import time
from datetime import datetime
from unittest.mock import Mock
import httpx
import pytest
from app.db import DB, Device, State, Measurement, Automation, AutomationRun, Command
from app.automations import tick, ZONE
from app.events import ingest, process_one

@pytest.fixture
def clock(monkeypatch):
    values=[time.time()]
    monkeypatch.setattr(time,'time',lambda:values[0])
    return values

@pytest.fixture
def adapter():
    result=Mock();result.command.return_value=True;result.control.return_value=True
    return result


def make_rule(clock,kind='temperature',name='Resfriar'):
    definition={'trigger':{'kind':kind,'device_id':'sensor','operator':'above','threshold':27,'duration_seconds':60,'hysteresis':.5,'allow_virtual':False,'time':'08:30','weekdays':list(range(7))},
                'actions':[{'device_id':'remote','type':'power','value':True}],'cooldown_seconds':60}
    with DB.begin() as db:
        device=db.get(Device,'sensor');device.config={**device.config,'expected_interval':10}
        rule=Automation(name=name,enabled=True,definition=definition,runtime={});db.add(rule);db.flush();return rule.id


def sample(clock,value):
    at=clock[0]
    with DB.begin() as db:
        db.add(Measurement(event_id=str(at)+str(value),device_id='sensor',property='temperature',value=value,unit='°C',observed=at,received=at))
        db.merge(State(device_id='sensor',property='temperature',value=value,unit='°C',source='reportado',observed=at,received=at))


def walk(clock,adapter,seconds,value=28):
    for _ in range(seconds//5):
        clock[0]+=5;sample(clock,value);tick(adapter)


def test_duration_latch_rearm_and_idempotent_worker(clock,adapter):
    make_rule(clock);sample(clock,28);tick(adapter)
    walk(clock,adapter,55);adapter.command.assert_not_called()
    walk(clock,adapter,5);assert adapter.command.call_count==1
    walk(clock,adapter,80);assert adapter.command.call_count==1
    clock[0]+=5;sample(clock,26);tick(adapter)
    walk(clock,adapter,65);assert adapter.command.call_count==2
    with DB() as db:assert db.query(AutomationRun).count()==2


def test_dip_between_worker_ticks_resets_duration(clock,adapter):
    make_rule(clock);sample(clock,28);tick(adapter);walk(clock,adapter,50)
    clock[0]+=1;sample(clock,26)
    clock[0]+=1;sample(clock,28)
    clock[0]+=3;tick(adapter)
    walk(clock,adapter,10);adapter.command.assert_not_called()
    walk(clock,adapter,50);assert adapter.command.call_count==1


def test_stale_data_and_restart_do_not_count_missing_time(clock,adapter):
    make_rule(clock);sample(clock,28);tick(adapter);walk(clock,adapter,25)
    clock[0]+=90;tick(adapter);adapter.command.assert_not_called()
    sample(clock,28);tick(adapter);walk(clock,adapter,55);adapter.command.assert_not_called()
    walk(clock,adapter,5);assert adapter.command.call_count==1


def test_hysteresis_prevents_temperature_chatter(clock,adapter):
    make_rule(clock);sample(clock,28);tick(adapter);walk(clock,adapter,60)
    walk(clock,adapter,70,value=26.8);walk(clock,adapter,70,value=28)
    assert adapter.command.call_count==1


def test_timeout_and_interrupted_runs_are_never_replayed(clock,adapter):
    make_rule(clock);adapter.command.side_effect=httpx.ReadTimeout('ambiguous')
    sample(clock,28);tick(adapter);walk(clock,adapter,60);walk(clock,adapter,90)
    assert adapter.command.call_count==1
    with DB() as db:assert db.query(AutomationRun).one().status=='resultado desconhecido'


def test_schedule_timezone_once_and_no_missed_catchup(clock,adapter):
    identifier=make_rule(clock,'schedule')
    clock[0]=datetime(2026,10,19,8,30,tzinfo=ZONE).timestamp();tick(adapter)
    clock[0]+=5;tick(adapter);assert adapter.command.call_count==1
    clock[0]=datetime(2026,10,20,8,31,tzinfo=ZONE).timestamp();tick(adapter)
    assert adapter.command.call_count==1
    clock[0]=datetime(2026,10,21,8,30,tzinfo=ZONE).timestamp();tick(adapter)
    assert adapter.command.call_count==2


def test_conflicting_rules_respect_device_interval(clock,adapter):
    make_rule(clock,name='One');make_rule(clock,name='Two')
    sample(clock,28);tick(adapter);walk(clock,adapter,60)
    assert adapter.command.call_count==1
    with DB() as db:assert sorted(r.status for r in db.query(AutomationRun))==['bloqueada','concluída']


def test_virtual_sensor_requires_explicit_opt_in(clock,adapter):
    make_rule(clock)
    with DB.begin() as db:
        device=db.get(Device,'sensor');device.config={**device.config,'virtual':True,'cloud_snapshot_without_timestamp':True}
    sample(clock,28);tick(adapter);walk(clock,adapter,90);adapter.command.assert_not_called()


def test_rule_crud_preview_enable_validation_and_permissions(logged,clock):
    body={'name':'Regra em rascunho','trigger':{'kind':'temperature','device_id':'sensor'},'actions':[],'cooldown_seconds':300}
    created=logged.post('/api/v1/automations',json=body)
    assert created.status_code==201 and not created.json()['enabled']
    identifier=created.json()['id']
    assert logged.patch(f'/api/v1/automations/{identifier}/enabled',json={'enabled':True}).status_code==422
    preview=logged.post(f'/api/v1/automations/{identifier}/preview').json();assert preview['sends_commands'] is False
    body['actions']=[{'device_id':'remote','type':'power','value':True}]
    assert logged.put(f'/api/v1/automations/{identifier}',json=body).status_code==200
    assert logged.patch(f'/api/v1/automations/{identifier}/enabled',json={'enabled':True}).json()['enabled']
    assert not logged.put(f'/api/v1/automations/{identifier}',json=body).json()['enabled']
    assert logged.post('/api/v1/automations',json=body,headers={'X-CSRF-Token':'bad'}).status_code==403
    assert logged.delete(f'/api/v1/automations/{identifier}').status_code==200
    assert logged.get('/api/v1/automations/history/runs').status_code==200


def test_unvalidated_action_cannot_enable(logged):
    body={'name':'No IR','trigger':{'kind':'schedule'},'actions':[{'device_id':'sensor','type':'power','value':True}]}
    rule=logged.post('/api/v1/automations',json=body).json()
    assert rule['issues']
    assert logged.patch('/api/v1/automations/'+rule['id']+'/enabled',json={'enabled':True}).status_code==422


def test_unknown_measurement_timestamp_does_not_drive_real_sensor_rule(clock,adapter):
    make_rule(clock);sample(clock,28)
    with DB.begin() as db:db.get(State,('sensor','temperature')).time_known=False
    tick(adapter)
    clock[0]+=10;tick(adapter)
    adapter.command.assert_not_called()


def test_explicit_virtual_opt_in_is_supported(clock,adapter):
    identifier=make_rule(clock)
    with DB.begin() as db:
        device=db.get(Device,'sensor');device.config={**device.config,'virtual':True,'cloud_snapshot_without_timestamp':True}
        rule=db.get(Automation,identifier);definition=dict(rule.definition);definition['trigger']={**definition['trigger'],'allow_virtual':True};rule.definition=definition
    sample(clock,28);tick(adapter);walk(clock,adapter,60)
    assert adapter.command.call_count==1


def test_simultaneous_workers_do_not_dispatch_twice(database,clock,adapter):
    if database.dialect.name=='sqlite':pytest.skip('Concurrent evaluator requires PostgreSQL')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    identifier=make_rule(clock)
    with DB.begin() as db:
        rule=db.get(Automation,identifier);definition=dict(rule.definition);definition['trigger']={**definition['trigger'],'duration_seconds':0};rule.definition=definition
    entered,release=Event(),Event()
    def hold(*args):
        entered.set();assert release.wait(10);return True
    adapter.command.side_effect=hold
    sample(clock,28)
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(tick,adapter)
        assert entered.wait(10)
        second=pool.submit(tick,adapter);second.result(timeout=10)
        release.set();first.result(timeout=10)
    assert adapter.command.call_count==1


def test_readonly_key_cannot_manage_rules(client):
    from app.db import ApiKey
    from app.security import digest
    with DB.begin() as db:db.add(ApiKey(hash=digest('readonly-automations'),name='rules-reader',control=False))
    headers={'Authorization':'Bearer readonly-automations'}
    assert client.get('/api/v1/automations',headers=headers).status_code==200
    assert client.post('/api/v1/automations',headers=headers,json={'name':'No','trigger':{'kind':'schedule'}}).status_code==403


def test_rule_can_power_on_and_set_temperature_in_same_run(clock,adapter):
    identifier=make_rule(clock)
    with DB.begin() as db:
        device=db.get(Device,'remote')
        device.config={'command':{'kind':'ir','profile':'tuya_ac_v2','infrared_id':'hub','remote_id':'ac','validated':True,'ac':{'validated':True,'temperature':{'min':16,'max':30}}}}
        rule=db.get(Automation,identifier);definition=dict(rule.definition)
        definition['trigger']={**definition['trigger'],'duration_seconds':0}
        definition['actions']=[*definition['actions'],{'device_id':'remote','type':'temperature','value':22}]
        rule.definition=definition
    sample(clock,28);tick(adapter)
    assert adapter.command.call_count==1 and adapter.control.call_count==1
    with DB() as db:
        assert db.query(AutomationRun).one().status=='concluída'
        assert db.query(Command).count()==2


def test_automation_can_send_a_whitelisted_tv_key_without_claiming_power(clock,adapter):
    identifier=make_rule(clock)
    with DB.begin() as db:
        device=db.get(Device,'remote');device.config={'command':{'kind':'ir','profile':'tuya_standard_ir','infrared_id':'hub','remote_id':'tv','keys_enabled':True,'keys_validated':True,'keys':[{'key':'Volume-','label':'Volume Down'}]}}
        rule=db.get(Automation,identifier);definition=dict(rule.definition);definition['trigger']={**definition['trigger'],'duration_seconds':0};definition['actions']=[{'device_id':'remote','type':'ir_key','value':'Volume-'}];rule.definition=definition
    sample(clock,28);tick(adapter);walk(clock,adapter,90)
    assert adapter.control.call_count==1 and adapter.command.call_count==0
    with DB() as db:
        assert db.get(State,('remote','power')) is None
        assert db.get(State,('remote','last_ir_key')).value=='Volume-'
