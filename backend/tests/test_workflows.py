import copy
import time
from datetime import datetime
from unittest.mock import Mock
import pytest
from app.db import DB, State, Measurement, Workflow, WorkflowRun, Command, ApiKey
from app.security import digest
from app.workflows import tick
from app.automations import ZONE


@pytest.fixture
def clock(monkeypatch):
    values = [time.time()]
    monkeypatch.setattr(time, 'time', lambda: values[0])
    return values


@pytest.fixture
def adapter():
    result = Mock(); result.command.return_value = True; result.control.return_value = True
    return result


def node(id, kind, data):
    return {'id': id, 'kind': kind, 'label': id, 'position': {'x': 0, 'y': 0}, 'data': data}


def graph(clock):
    return {'name': 'Ambiente', 'revision': 0, 'cooldown_seconds': 60, 'nodes': [
        node('temp', 'trigger', {'kind': 'temperature', 'device_id': 'sensor', 'duration_seconds': 0}),
        node('action', 'action', {'device_id': 'remote', 'type': 'power', 'value': True})],
        'edges': [{'id': 'e1', 'source': 'temp', 'target': 'action', 'port': 'out'}]}


def reading(clock, value=28, prop='temperature', known=True):
    with DB.begin() as db:
        db.merge(State(device_id='sensor', property=prop, value=value, source='reportado', observed=clock[0], received=clock[0], time_known=known))
        db.add(Measurement(event_id=str(clock[0])+prop+str(value), device_id='sensor', property=prop, value=value, observed=clock[0], received=clock[0], time_known=known))


def save(client, body, enable=True):
    r = client.put('/api/v1/automation-flow', json=body)
    assert r.status_code == 200, r.text
    f = r.json()
    if enable:
        r = client.patch('/api/v1/automation-flow/enabled', json={'revision': f['revision'], 'enabled': True})
        assert r.status_code == 200, r.text
        f = r.json()
    return f


def runs():
    with DB() as db: return db.query(WorkflowRun).order_by(WorkflowRun.created).all()


def test_disabled_and_disconnected_are_inert(logged, clock, adapter):
    body = graph(clock); save(logged, body, False); reading(clock); tick(adapter)
    adapter.command.assert_not_called(); assert not runs()
    body['revision'] = 1; body['nodes'].append(node('loose', 'action', {'device_id': 'missing', 'type': 'power', 'value': True}))
    save(logged, body); tick(adapter)
    assert adapter.command.call_count == 1
    assert len(runs()[0].state['done']) == 2


def test_two_triggers_share_one_action_or(logged, clock, adapter):
    body = graph(clock)
    at = datetime.fromtimestamp(clock[0]+65, ZONE).strftime('%H:%M')
    body['nodes'].append(node('schedule', 'trigger', {'kind': 'schedule', 'time': at}))
    body['edges'].append({'id': 'e2', 'source': 'schedule', 'target': 'action', 'port': 'out'})
    save(logged, body); reading(clock); tick(adapter); assert adapter.command.call_count == 1
    clock[0] += 65; reading(clock, 25); tick(adapter)
    assert adapter.command.call_count == 2; assert len(runs()) == 2
    tick(adapter); assert adapter.command.call_count == 2


def test_durable_wait_restart_and_once(logged, clock, adapter):
    body = graph(clock); body['nodes'].append(node('wait', 'delay', {'seconds': 120}))
    body['edges'] = [{'id': 'e1', 'source': 'temp', 'target': 'wait'}, {'id': 'e2', 'source': 'wait', 'target': 'action'}]
    save(logged, body); reading(clock); tick(adapter)
    assert runs()[0].status == 'aguardando'; adapter.command.assert_not_called()
    clock[0] += 119; tick(adapter); adapter.command.assert_not_called()
    # Nothing is stored in memory: a new adapter/worker resumes the persisted deadline.
    other = Mock(); other.command.return_value = True
    clock[0] += 1; tick(other); assert other.command.call_count == 1; assert runs()[0].status == 'concluída'
    tick(other); assert other.command.call_count == 1


def test_disable_cancels_wait_without_replay(logged, clock, adapter):
    body = graph(clock); body['nodes'].append(node('wait', 'delay', {'seconds': 10}))
    body['edges'] = [{'id': 'e1', 'source': 'temp', 'target': 'wait'}, {'id': 'e2', 'source': 'wait', 'target': 'action'}]
    f = save(logged, body); reading(clock); tick(adapter)
    r = logged.patch('/api/v1/automation-flow/enabled', json={'revision': f['revision'], 'enabled': False}); assert r.status_code == 200
    clock[0] += 20; tick(adapter); adapter.command.assert_not_called(); assert runs()[0].status == 'cancelada'


def test_condition_branches_and_stale_blocks(logged, clock, adapter):
    body = graph(clock)
    body['nodes'].extend([node('condition', 'condition', {'device_id': 'sensor', 'property': 'humidity', 'threshold': 70}), node('off', 'action', {'device_id': 'remote', 'type': 'power', 'value': False})])
    body['edges'] = [{'id': 'e1', 'source': 'temp', 'target': 'condition'}, {'id': 'yes', 'source': 'condition', 'target': 'action', 'port': 'yes'}, {'id': 'no', 'source': 'condition', 'target': 'off', 'port': 'no'}]
    save(logged, body); reading(clock); reading(clock, 50, 'humidity'); tick(adapter)
    assert adapter.command.call_args.args[1] is False
    assert 'action' not in runs()[0].state['done']


def test_condition_unknown_never_means_false(logged, clock, adapter):
    body = graph(clock); body['nodes'].append(node('condition', 'condition', {'device_id': 'sensor', 'property': 'humidity'}))
    body['edges'] = [{'id': 'e1', 'source': 'temp', 'target': 'condition'}, {'id': 'no', 'source': 'condition', 'target': 'action', 'port': 'no'}]
    save(logged, body); reading(clock); tick(adapter)
    adapter.command.assert_not_called(); assert runs()[0].status == 'bloqueada'


def test_humidity_trigger(logged, clock, adapter):
    body = graph(clock); body['nodes'][0]['data'].update(kind='humidity', threshold=70)
    save(logged, body); reading(clock, 75, 'humidity'); tick(adapter)
    assert adapter.command.call_count == 1


def test_duration_dip_and_rearm(logged, clock, adapter):
    body = graph(clock); body['nodes'][0]['data']['duration_seconds'] = 30
    save(logged, body); reading(clock); tick(adapter)
    for _ in range(5): clock[0] += 5; reading(clock); tick(adapter)
    adapter.command.assert_not_called()
    clock[0] += 1; reading(clock, 25)
    clock[0] += 1; reading(clock, 28)
    clock[0] += 3; tick(adapter)
    for _ in range(5): clock[0] += 5; reading(clock); tick(adapter)
    adapter.command.assert_not_called()
    clock[0] += 5; reading(clock); tick(adapter); assert adapter.command.call_count == 1


def test_unknown_timestamp_blocks_trigger(logged, clock, adapter):
    save(logged, graph(clock)); reading(clock, known=False); tick(adapter)
    adapter.command.assert_not_called(); assert not runs()


def test_converging_paths_execute_once_per_run(logged, clock, adapter):
    body = graph(clock)
    body['nodes'].extend([node('a', 'delay', {'seconds': 10}), node('b', 'delay', {'seconds': 15})])
    body['edges'] = [{'id': 'ta', 'source': 'temp', 'target': 'a'}, {'id': 'tb', 'source': 'temp', 'target': 'b'}, {'id': 'aa', 'source': 'a', 'target': 'action'}, {'id': 'ba', 'source': 'b', 'target': 'action'}]
    save(logged, body); reading(clock); tick(adapter)
    clock[0] += 10; tick(adapter); assert adapter.command.call_count == 1
    clock[0] += 5; tick(adapter); assert adapter.command.call_count == 1
    assert runs()[0].status == 'concluída'


def test_timeout_stops_chain_and_never_retries(logged, clock, adapter):
    body = graph(clock); body['nodes'].append(node('off', 'action', {'device_id': 'remote', 'type': 'power', 'value': False})); body['edges'].append({'id': 'e2', 'source': 'action', 'target': 'off'})
    save(logged, body); reading(clock); adapter.command.side_effect = TimeoutError(); tick(adapter); tick(adapter)
    assert adapter.command.call_count == 1; assert runs()[0].status == 'resultado desconhecido'


def test_interrupted_claim_is_unknown_without_resend(logged, clock, adapter):
    f = save(logged, graph(clock)); reading(clock)
    with DB.begin() as db:
        graph_ = db.get(Workflow, 'main').graph
        db.add(WorkflowRun(revision=f['revision'], trigger_id='old', occurrence='x', graph=graph_, state={'queue': [], 'done': [], 'log': [], 'running': 'action'}, status='executando', created=clock[0]-100, updated=clock[0]-100))
    reading(clock, 20); tick(adapter); adapter.command.assert_not_called(); assert runs()[0].status == 'resultado desconhecido'


@pytest.mark.parametrize('fault', ['cycle', 'missing', 'port', 'duplicate', 'into_trigger'])
def test_invalid_connections_rejected(logged, clock, fault):
    body = graph(clock)
    if fault == 'cycle': body['edges'].append({'id': 'e2', 'source': 'action', 'target': 'action'})
    if fault == 'missing': body['edges'][0]['target'] = 'unknown'
    if fault == 'port': body['edges'][0]['port'] = 'yes'
    if fault == 'duplicate': body['edges'].append({**body['edges'][0], 'id': 'e2'})
    if fault == 'into_trigger': body['edges'].append({'id': 'e2', 'source': 'action', 'target': 'temp'})
    assert logged.put('/api/v1/automation-flow', json=body).status_code == 422


def test_optimistic_edit_disables_and_validate_has_no_side_effects(logged, clock, adapter):
    body = graph(clock); f = save(logged, body)
    assert logged.put('/api/v1/automation-flow', json=body).status_code == 409
    body['revision'] = f['revision']
    assert logged.post('/api/v1/automation-flow/validate', json=body).json()['sends_commands'] is False
    with DB() as db: assert db.get(Workflow, 'main').enabled
    save(logged, body, False); reading(clock); tick(adapter); adapter.command.assert_not_called()


def test_readonly_key_and_csrf_cannot_modify(logged, clock):
    body = graph(clock)
    with DB.begin() as db: db.add(ApiKey(hash=digest('reader'), name='reader', control=False))
    assert logged.put('/api/v1/automation-flow', json=body, headers={'X-CSRF-Token': 'bad'}).status_code == 403
    assert logged.get('/api/v1/automation-flow', headers={'Authorization': 'Bearer reader'}).status_code == 200
    assert logged.put('/api/v1/automation-flow', json=body, headers={'Authorization': 'Bearer reader'}).status_code == 403


def test_device_protection_between_simultaneous_triggers(logged, clock, adapter):
    body = graph(clock); second = copy.deepcopy(body['nodes'][0]); second['id'] = 'second'; second['label'] = 'second'; body['nodes'].append(second)
    body['edges'].append({'id': 'e2', 'source': 'second', 'target': 'action'})
    save(logged, body); reading(clock); tick(adapter)
    assert adapter.command.call_count == 1
    assert sorted(r.status for r in runs()) == ['bloqueada', 'concluída']
