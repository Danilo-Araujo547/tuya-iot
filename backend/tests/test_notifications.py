import json
import time
from datetime import datetime
from unittest.mock import Mock
import httpx
import pytest
from app import notifications as n
from app.workflows import tick
from app.automations import ZONE
from app.db import DB, WorkflowRun, Workflow, ApiKey
from app.security import digest


@pytest.fixture(autouse=True)
def private_config(tmp_path, monkeypatch):
    monkeypatch.setenv('NOTIFICATION_CONFIG_DIR', str(tmp_path/'notifications'))
    for channel in ('WHATSAPP', 'TELEGRAM', 'WEBHOOK'):
        for suffix in ('_API_TOKEN', '_API_URL', '_API_TOKEN_FILE', '_API_URL_FILE'): monkeypatch.delenv(channel+suffix, raising=False)


def configure(logged, channel='whatsapp'):
    token = '123456:secret_test' if channel == 'telegram' else 'private-test-token'
    r = logged.put('/api/v1/notification-connections/'+channel, json={'url': 'http://172.16.0.59:3011' if channel == 'whatsapp' else 'https://example.com/hook?key=private-url', 'token': token})
    assert r.status_code == 200, r.text
    return token


def transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(n.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def data(channel='whatsapp', **kwargs):
    return n.Notification(channel=channel, destination='5511999999999' if channel == 'whatsapp' else '-1001234567890', message='Temperatura alta', **kwargs).model_dump()


def context(): return {'run_id': 'run-1', 'node_id': 'notification', 'flow_name': 'Ambiente', 'revision': 1, 'timestamp': time.time()}


@pytest.mark.parametrize('destination_type,destination', [('phone','5511999999999'), ('group_id','120363123456789@g.us'), ('chat_id','123456789@lid')])
def test_whatsapp_exact_contract_and_destination(logged, monkeypatch, destination_type, destination):
    token = configure(logged); calls = []
    def handle(request):
        calls.append(request)
        assert request.url.path == '/api/send'
        assert request.headers['Authorization'] == 'Bearer '+token
        assert json.loads(request.content) == {destination_type: destination, 'message': 'Temperatura alta'}
        return httpx.Response(200, json={'success': True, 'accepted': True, 'delivery_state': 'sent', 'whatsapp_message_id': 'wa-1'})
    transport(monkeypatch, handle)
    message = data(); message.update(destination_type=destination_type, destination=destination)
    r = n.send_notification(message, context())
    assert r['status'] == 'aceito pelo provedor'; assert r['provider_message_id'] == 'wa-1'; assert len(calls) == 1


def test_telegram_real_bot_api_contract(logged, monkeypatch):
    token = configure(logged, 'telegram')
    def handle(request):
        assert str(request.url) == 'https://api.telegram.org/bot'+token+'/sendMessage'
        assert json.loads(request.content) == {'chat_id': '-1001234567890', 'text': 'Temperatura alta'}
        return httpx.Response(200, json={'ok': True, 'result': {'message_id': 42}})
    transport(monkeypatch, handle)
    assert n.send_notification(data('telegram'), context())['provider_message_id'] == '42'


def test_webhook_context_auth_and_idempotency(logged, monkeypatch):
    configure(logged, 'webhook')
    def handle(request):
        assert request.headers['Idempotency-Key'] == 'run-1:notification'
        assert request.headers['Authorization'] == 'Bearer private-test-token'
        body = json.loads(request.content)
        assert body['event'] == 'automation.notification' and body['run_id'] == 'run-1' and body['message'] == 'Temperatura alta'
        return httpx.Response(204)
    transport(monkeypatch, handle)
    assert n.send_notification(data('webhook'), context())['status'] == 'aceito pelo provedor'


@pytest.mark.parametrize('code,body,status', [(401,{},'falhou'),(503,{},'falhou'),(500,{},'resultado desconhecido'),(200,{'success':False,'accepted':False},'falhou'),(302,{},'falhou'),(200,{},'falhou')])
def test_provider_errors_no_retries(logged, monkeypatch, code, body, status):
    configure(logged); calls = []
    def handle(request): calls.append(request); return httpx.Response(code, json=body)
    transport(monkeypatch, handle)
    assert n.send_notification(data(), context())['status'] == status; assert len(calls) == 1


def test_timeout_redacted_and_not_retried(logged, monkeypatch):
    token = configure(logged); calls = []
    def handle(request): calls.append(request); raise httpx.ReadTimeout('https://secret-url/'+token)
    transport(monkeypatch, handle)
    r = n.send_notification(data(), context())
    assert r['status'] == 'resultado desconhecido'; assert token not in json.dumps(r); assert len(calls) == 1


def test_credential_persistence_redaction_and_preserve(logged):
    token = configure(logged, 'webhook')
    listing = logged.get('/api/v1/notification-connections')
    assert token not in listing.text and 'private-url' not in listing.text
    assert n.connection('webhook')['token'] == token
    r = logged.put('/api/v1/notification-connections/webhook', json={'url':'','token':''})
    assert r.status_code == 200 and n.connection('webhook')['token'] == token
    r = logged.put('/api/v1/notification-connections/webhook', json={'clear_token':True})
    assert r.status_code == 200 and n.connection('webhook')['token'] == ''


def test_invalid_url_token_permissions_and_csrf(logged):
    assert logged.put('/api/v1/notification-connections/webhook', json={'url':'file:///etc/passwd'}).status_code == 422
    assert logged.put('/api/v1/notification-connections/webhook', json={'url':'https://user:pass@example.com'}).status_code == 422
    assert logged.put('/api/v1/notification-connections/telegram', json={'token':'invalid'}).status_code == 422
    assert logged.put('/api/v1/notification-connections/whatsapp', json={'token':'secret'}, headers={'X-CSRF-Token':'bad'}).status_code == 403
    with DB.begin() as db: db.add(ApiKey(hash=digest('reader'), name='reader', control=False))
    assert logged.get('/api/v1/notification-connections', headers={'Authorization':'Bearer reader'}).status_code == 403
    assert logged.put('/api/v1/notification-connections/whatsapp', json={'token':'secret'}, headers={'Authorization':'Bearer reader'}).status_code == 403


def flow(now):
    return {'name':'Notificar','revision':0,'cooldown_seconds':60,'nodes':[
        {'id':'trigger','kind':'trigger','label':'Horário','position':{'x':0,'y':0},'data':{'kind':'schedule','time':datetime.fromtimestamp(now,ZONE).strftime('%H:%M')}},
        {'id':'notify','kind':'notification','label':'Aviso','position':{'x':300,'y':0},'data':data()},
        {'id':'action','kind':'action','label':'Ar','position':{'x':600,'y':0},'data':{'device_id':'remote','type':'power','value':True}}],
        'edges':[{'id':'tn','source':'trigger','target':'notify'},{'id':'na','source':'notify','target':'action'}]}


@pytest.mark.parametrize('accepted',[True,False])
def test_durable_notification_execution_once_and_stop_chain(logged, monkeypatch, accepted):
    now = time.time(); configure(logged); calls = []
    def handle(request):
        calls.append(request)
        if not accepted: raise httpx.ReadTimeout('unknown')
        return httpx.Response(200,json={'success':True,'accepted':True})
    transport(monkeypatch,handle)
    # TestClient remains its own existing transport; outbound delivery uses the mock above.
    r = logged.put('/api/v1/automation-flow',json=flow(now)); assert r.status_code == 200,r.text
    r = logged.patch('/api/v1/automation-flow/enabled',json={'revision':r.json()['revision'],'enabled':True}); assert r.status_code == 200,r.text
    adapter = Mock(); adapter.command.return_value = True
    tick(adapter,now); tick(adapter,now)
    assert len(calls) == 1; assert adapter.command.call_count == (1 if accepted else 0)
    with DB() as db:
        run = db.query(WorkflowRun).one(); assert run.status == ('concluída' if accepted else 'resultado desconhecido')
        assert 'private-test-token' not in json.dumps(run.graph) and 'private-test-token' not in json.dumps(run.state)


def test_notification_only_flow_and_missing_config_block_activation(logged):
    body = flow(time.time()); body['nodes'] = body['nodes'][:2]; body['edges'] = body['edges'][:1]
    r = logged.put('/api/v1/automation-flow',json=body); assert r.status_code == 200
    revision = r.json()['revision']
    assert logged.patch('/api/v1/automation-flow/enabled',json={'revision':revision,'enabled':True}).status_code == 422
    configure(logged)
    assert logged.patch('/api/v1/automation-flow/enabled',json={'revision':revision,'enabled':True}).status_code == 200


def test_invalid_recipient_message_and_timeout():
    assert n.notification_issues({**data(),'destination_type':'group_id','destination':'https://invite.link'})
    assert n.notification_issues({**data(),'message':'   '})
    with pytest.raises(ValueError): n.Notification(timeout_seconds=100)
