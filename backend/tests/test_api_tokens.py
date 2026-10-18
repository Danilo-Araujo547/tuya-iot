import json
import sys
import pytest
from app.cli import main
from app.db import DB, ApiKey
from app.security import digest


def cli(monkeypatch,capsys,*args):
    monkeypatch.setattr(sys,'argv',['app.cli',*args])
    main()
    return capsys.readouterr().out.strip()


def test_terminal_token_read_list_and_revoke(client,monkeypatch,capsys):
    token=cli(monkeypatch,capsys,'create-token','--name','reader')
    assert len(token)>=40
    headers={'Authorization':'Bearer '+token}
    assert client.get('/api/v1/devices',headers=headers).status_code==200
    assert client.get('/api/v1/automation-flow',headers=headers).status_code==200
    assert client.get('/api/v1/automation-flow/runs',headers=headers).status_code==200
    listed=cli(monkeypatch,capsys,'list-tokens')
    assert token not in listed and digest(token) not in listed
    assert json.loads(listed)==[{'name':'reader','read':True,'control':False,'automations':False}]
    with DB() as db:
        assert db.get(ApiKey,digest(token)).name=='reader'
    cli(monkeypatch,capsys,'revoke-token','--name','reader')
    assert client.get('/api/v1/devices',headers=headers).status_code==401


def test_automation_scope_is_separate_from_device_control(client,monkeypatch,capsys):
    device_token=cli(monkeypatch,capsys,'create-token','--name','controller','--control')
    automation_token=cli(monkeypatch,capsys,'create-token','--name','flow','--automations')
    body={'name':'Integration flow','revision':0,'cooldown_seconds':300,'nodes':[],'edges':[]}
    device_headers={'Authorization':'Bearer '+device_token}
    flow_headers={'Authorization':'Bearer '+automation_token}
    assert client.put('/api/v1/automation-flow',json=body,headers=device_headers).status_code==403
    assert client.post('/api/v1/devices/remote/control/commands',json={'type':'power','value':True},headers={**flow_headers,'Idempotency-Key':'scope-test-123'}).status_code==403
    result=client.put('/api/v1/automation-flow',json=body,headers=flow_headers)
    assert result.status_code==200 and result.json()['enabled'] is False
    body['revision']=result.json()['revision']
    assert client.post('/api/v1/automation-flow/validate',json=body,headers=flow_headers).status_code==200
    assert client.patch('/api/v1/automation-flow/enabled',json={'enabled':False,'revision':body['revision']},headers=flow_headers).status_code==200
    assert client.put('/api/v1/integrations/devices',json={'id':'no','name':'no'},headers=flow_headers).status_code==403
    assert client.get('/api/v1/notification-connections',headers=flow_headers).status_code==403
    assert client.put('/api/v1/notification-connections/webhook',json={'url':'https://example.com/hook'},headers=flow_headers).status_code==403


def test_token_aliases_and_duplicate_name(client,monkeypatch,capsys):
    token=cli(monkeypatch,capsys,'create-key','--name','old-cli','--control','--automations')
    listed=json.loads(cli(monkeypatch,capsys,'list-keys'))
    assert listed[0]['control'] and listed[0]['automations']
    with pytest.raises(SystemExit):
        cli(monkeypatch,capsys,'create-token','--name','old-cli')
    capsys.readouterr()
    assert client.get('/api/v1/devices',headers={'Authorization':'Bearer '+token}).status_code==200
    cli(monkeypatch,capsys,'revoke-key','--name','old-cli')
    assert client.get('/api/v1/devices',headers={'Authorization':'Bearer '+token}).status_code==401
