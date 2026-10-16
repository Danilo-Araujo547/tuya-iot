"""One durable DAG. Each trigger starts an independent run; convergent edges mean OR.

Wait nodes persist deadlines, never sleep. External actions are claimed before I/O;
an interrupted claim becomes unknown and is never replayed automatically.
"""
import copy
import math
import time
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from .db import DB, Workflow, WorkflowRun, Automation, Device, State, health, take_rate
from .automations import Trigger, RuleAction, admin, evaluate
from .security import authenticate
from .control_profiles import validate_action
from .commands import submit_action
from .notifications import Notification, notification_issues, send_notification

router = APIRouter(prefix='/api/v1/automation-flow')
ACTIVE = ('pendente', 'aguardando', 'executando')


class FlowTrigger(Trigger):
    kind: Literal['temperature', 'humidity', 'schedule'] = 'temperature'
    threshold: float = Field(default=27, ge=-50, le=100, allow_inf_nan=False)
    @model_validator(mode='after')
    def source(self):
        if self.kind != 'schedule' and not self.device_id:
            raise ValueError('Selecione o sensor')
        return self


class Condition(BaseModel):
    device_id: str = Field(default='', max_length=128)
    property: Literal['temperature', 'humidity'] = 'temperature'
    operator: Literal['above', 'below'] = 'above'
    threshold: float = Field(default=27, ge=-50, le=100, allow_inf_nan=False)
    allow_virtual: bool = False


class Delay(BaseModel):
    seconds: int = Field(default=60, ge=1, le=86400)


class Position(BaseModel):
    x: float = Field(ge=-50000, le=50000, allow_inf_nan=False)
    y: float = Field(ge=-50000, le=50000, allow_inf_nan=False)


class Node(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    kind: Literal['trigger', 'delay', 'condition', 'action', 'notification']
    label: str = Field(min_length=1, max_length=100)
    position: Position
    data: dict
    @model_validator(mode='after')
    def config(self):
        model = {'trigger': FlowTrigger, 'delay': Delay, 'condition': Condition, 'action': RuleAction, 'notification': Notification}[self.kind]
        self.data = model.model_validate(self.data).model_dump()
        return self


class Edge(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    source: str
    target: str
    port: Literal['out', 'yes', 'no'] = 'out'


class FlowBody(BaseModel):
    name: str = Field(default='Meu ambiente', min_length=1, max_length=100)
    revision: int = Field(default=0, ge=0)
    cooldown_seconds: int = Field(default=300, ge=60, le=86400)
    nodes: list[Node] = Field(default_factory=list, max_length=60)
    edges: list[Edge] = Field(default_factory=list, max_length=150)
    @model_validator(mode='after')
    def topology(self):
        nodes = {n.id: n for n in self.nodes}
        if len(nodes) != len(self.nodes) or len({e.id for e in self.edges}) != len(self.edges):
            raise ValueError('Identificadores duplicados')
        seen = set(); outgoing = {n: [] for n in nodes}; indegree = {n: 0 for n in nodes}
        for e in self.edges:
            if e.source not in nodes or e.target not in nodes:
                raise ValueError('Conexão aponta para bloco inexistente')
            if nodes[e.target].kind == 'trigger':
                raise ValueError('Gatilhos não recebem conexões')
            if (nodes[e.source].kind == 'condition') != (e.port in ('yes', 'no')):
                raise ValueError('Escolha a saída correta do bloco')
            key = (e.source, e.target, e.port)
            if key in seen: raise ValueError('Conexão duplicada')
            seen.add(key); outgoing[e.source].append(e.target); indegree[e.target] += 1
        queue = [n for n in nodes if indegree[n] == 0]; count = 0
        while queue:
            n = queue.pop(); count += 1
            for target in outgoing[n]:
                indegree[target] -= 1
                if indegree[target] == 0: queue.append(target)
        if count != len(nodes): raise ValueError('O fluxo não permite ciclos. Use os gatilhos para iniciar novas execuções')
        return self


class FlowSwitch(BaseModel):
    enabled: bool
    revision: int


def reachable(graph, root):
    result = set(); queue = [root]
    while queue:
        current = queue.pop()
        if current in result: continue
        result.add(current)
        queue.extend(e['target'] for e in graph['edges'] if e['source'] == current)
    return result


def sample(db, data, now):
    device = db.get(Device, data['device_id'])
    state = db.get(State, (data['device_id'], data['property']))
    age = device.config.get('expected_interval', 300)*3 if device else 0
    online = db.get(State, (data['device_id'], 'online'))
    virtual = device and device.config.get('virtual') and data.get('allow_virtual')
    if not device or not state or state.source != 'reportado' or (device.config.get('virtual') and not virtual) or (not state.time_known and not virtual) or type(state.value) not in (int, float) or not math.isfinite(state.value) or not -5 <= now-state.observed <= age or (online and online.value is False and now-online.observed < age):
        return None
    return state.value


def issues(db, graph):
    problems = []; active = set(); nodes = {n['id']: n for n in graph['nodes']}
    triggers = [n for n in graph['nodes'] if n['kind'] == 'trigger' and any(nodes[k]['kind'] in ('action', 'notification') for k in reachable(graph, n['id']))]
    if not triggers: problems.append('Conecte um gatilho a uma ação')
    for trigger in triggers: active |= reachable(graph, trigger['id'])
    for identifier in active:
        node = nodes[identifier]; data = node['data']; problem = None
        if node['kind'] == 'action':
            target = db.get(Device, data['device_id'])
            try:
                if not target: raise HTTPException(422, 'Dispositivo não cadastrado')
                validate_action(target, {'type': data['type'], 'value': data['value']})
            except HTTPException as exc: problem = exc.detail
        elif node['kind'] == 'notification':
            problem = '; '.join(notification_issues(data)) or None
        elif node['kind'] == 'condition' or (node['kind'] == 'trigger' and data['kind'] != 'schedule'):
            prop = data.get('property', data.get('kind')); device = db.get(Device, data['device_id'])
            if not device or not any(p.get('property') == prop for p in device.config.get('properties', {}).values()): problem = 'Sensor não configurado para esta propriedade'
            elif device.config.get('virtual') and not data.get('allow_virtual'): problem = 'Autorize o sensor virtual explicitamente'
            elif device.config.get('cloud_snapshot_without_timestamp') and not device.config.get('virtual'): problem = 'O sensor não informa o horário da medição'
        if problem: problems.append(node['label']+': '+str(problem))
    return problems


def initial(db):
    # A read-only import preview preserves previous rules and all device IDs.
    nodes = []; edges = []
    for index, rule in enumerate(db.query(Automation).order_by(Automation.updated).all()[:10]):
        start = f'legacy_{index}'; y = index*220
        nodes.append({'id': start, 'kind': 'trigger', 'label': rule.name, 'position': {'x': 80, 'y': y+80}, 'data': rule.definition['trigger']})
        previous = start
        for j, action in enumerate(rule.definition['actions']):
            target = f'{start}_action_{j}'
            nodes.append({'id': target, 'kind': 'action', 'label': 'Ação do dispositivo', 'position': {'x': 420+j*320, 'y': y+80}, 'data': action})
            edges.append({'id': f'{target}_edge', 'source': previous, 'target': target, 'port': 'out'}); previous = target
    return {'name': 'Meu ambiente', 'revision': 0, 'enabled': False, 'cooldown_seconds': 300, 'nodes': nodes, 'edges': edges, 'runtime': {}, 'issues': [], 'imported': bool(nodes)}


def serialize(db, flow):
    return {'name': flow.name, 'enabled': flow.enabled, 'revision': flow.revision, **flow.graph, 'runtime': flow.runtime, 'issues': issues(db, flow.graph), 'updated': flow.updated}


@router.get('')
def get_flow(request: Request):
    authenticate(request)
    with DB() as db:
        flow = db.get(Workflow, 'main')
        return serialize(db, flow) if flow else initial(db)


@router.put('')
def save_flow(body: FlowBody, request: Request):
    admin(request)
    with DB.begin() as db:
        # Serialize first creation as well as updates across processes.
        from .db import Rate
        db.execute(select(Rate).where(Rate.key == 'commands').with_for_update()).scalar_one()
        flow = db.execute(select(Workflow).where(Workflow.id == 'main').with_for_update()).scalar_one_or_none()
        if body.revision != (flow.revision if flow else 0): raise HTTPException(409, 'O fluxo foi alterado em outra aba. Recarregue antes de salvar')
        if not flow: flow = Workflow(id='main', revision=0); db.add(flow)
        flow.name = body.name; flow.graph = body.model_dump(exclude={'name', 'revision'}); flow.enabled = False
        flow.revision += 1; flow.runtime = {}; flow.updated = time.time()
        for rule in db.query(Automation).filter_by(enabled=True): rule.enabled = False
        for run in db.query(WorkflowRun).filter(WorkflowRun.status.in_(('pendente', 'aguardando'))):
            run.status = 'cancelada'; run.updated = time.time()
        db.flush(); return serialize(db, flow)


@router.patch('/enabled')
def switch_flow(body: FlowSwitch, request: Request):
    admin(request)
    with DB.begin() as db:
        flow = db.execute(select(Workflow).where(Workflow.id == 'main').with_for_update()).scalar_one_or_none()
        if not flow or flow.revision != body.revision: raise HTTPException(409, 'Salve ou recarregue o fluxo primeiro')
        if body.enabled:
            errors = issues(db, flow.graph)
            if errors: raise HTTPException(422, '; '.join(errors))
        if flow.enabled != body.enabled:
            flow.runtime = {}; flow.revision += 1
            for run in db.query(WorkflowRun).filter(WorkflowRun.status.in_(('pendente', 'aguardando'))): run.status = 'cancelada'; run.updated = time.time()
        flow.enabled = body.enabled; flow.updated = time.time(); db.flush()
        return serialize(db, flow)


@router.get('/runs')
def list_runs(request: Request):
    authenticate(request)
    with DB() as db:
        return [{'id': r.id, 'revision': r.revision, 'trigger_id': r.trigger_id, 'status': r.status, 'created': r.created, 'state': r.state} for r in db.query(WorkflowRun).order_by(WorkflowRun.created.desc()).limit(60)]


@router.post('/validate')
def validate(body: FlowBody, request: Request):
    admin(request)
    with DB() as db:
        return {'issues': issues(db, body.model_dump()), 'sends_commands': False}


def tick(adapter, now=None):
    now = time.time() if now is None else now
    with DB.begin() as db:
        flow = db.execute(select(Workflow).where(Workflow.id == 'main').with_for_update(skip_locked=True)).scalar_one_or_none()
        if not flow or not flow.enabled: return
        runtime = copy.deepcopy(flow.runtime or {}); graph = flow.graph
        count = db.query(WorkflowRun).filter(WorkflowRun.status.in_(ACTIVE)).count()
        for node in graph['nodes']:
            if node['kind'] != 'trigger' or not any(n['kind'] in ('action', 'notification') and n['id'] in reachable(graph, node['id']) for n in graph['nodes']): continue
            data = node['data']; prop = data['kind']
            # Only this branch's source needs to be available; an unrelated stale sensor never blocks it.
            if prop != 'schedule' and sample(db, {**data, 'property': prop}, now) is None:
                runtime[node['id']] = {**runtime.get(node['id'], {}), 'since': None, 'last_sample': 0, 'reason': 'Aguardando medição válida e atualizada', 'last_tick': now}; continue
            trigger = {**data, 'kind': 'schedule' if prop == 'schedule' else 'temperature', 'property': prop}
            temp = Automation(definition={'trigger': trigger, 'cooldown_seconds': graph['cooldown_seconds']}, runtime=runtime.get(node['id'], {}))
            due, _ = evaluate(db, temp, now); runtime[node['id']] = temp.runtime
            if due:
                if count >= 100:
                    runtime[node['id']]['reason'] = 'Limite de 100 execuções pendentes; ocorrência ignorada'; continue
                db.add(WorkflowRun(revision=flow.revision, trigger_id=node['id'], occurrence=due, graph=graph,
                                   state={'queue': [{'node': node['id'], 'at': now}], 'done': [], 'log': []}, created=now, updated=now)); count += 1
        flow.runtime = runtime
    with DB() as db:
        ids = [r.id for r in db.query(WorkflowRun).filter(WorkflowRun.status.in_(ACTIVE)).order_by(WorkflowRun.created).limit(100)]
    for identifier in ids:
        for _ in range(60):
            if not advance(identifier, adapter, now): break
    health('workflow', {'alive': True, 'at': now, 'active': len(ids)})


def advance(identifier, adapter, now):
    action = None
    with DB.begin() as db:
        run = db.execute(select(WorkflowRun).where(WorkflowRun.id == identifier).with_for_update(skip_locked=True)).scalar_one_or_none()
        if not run or run.status not in ACTIVE: return False
        flow = db.get(Workflow, 'main')
        if run.status == 'executando':
            if now-run.updated > 60:
                run.status = 'resultado desconhecido'; run.updated = now
                run.state = {**run.state, 'log': [*run.state.get('log', []), {'node': run.state.get('running'), 'status': 'resultado desconhecido', 'detail': 'Processamento interrompido; envio não repetido', 'at': now}]}
            return False
        if not flow or not flow.enabled or flow.revision != run.revision:
            run.status = 'cancelada'; run.updated = now; return False
        state = copy.deepcopy(run.state); queue = state['queue']; done = state['done']
        queue[:] = [q for q in queue if q['node'] not in done]
        item = next((q for q in queue if q['at'] <= now), None)
        if not item:
            run.state = state; run.status = 'aguardando' if queue else 'concluída'; run.updated = now; return False
        queue.remove(item); node = next(n for n in run.graph['nodes'] if n['id'] == item['node']); data = node['data']
        if node['kind'] == 'delay' and not item.get('waiting'):
            queue.append({'node': node['id'], 'at': now+data['seconds'], 'waiting': True})
            state['log'].append({'node': node['id'], 'status': 'aguardando', 'until': now+data['seconds'], 'at': now})
            run.state = state; run.status = 'aguardando'; run.updated = now; return True
        port = 'out'
        if node['kind'] == 'condition':
            value = sample(db, data, now)
            if value is None:
                run.state = {**state, 'log': [*state['log'], {'node': node['id'], 'status': 'bloqueada', 'detail': 'Sem medição válida para avaliar a condição', 'at': now}]}
                run.status = 'bloqueada'; run.updated = now; return False
            matches = value > data['threshold'] if data['operator'] == 'above' else value < data['threshold']
            port = 'yes' if matches else 'no'
        if node['kind'] in ('action', 'notification'):
            # Persist the claim before any network call. Other workers cannot execute this run.
            state['running'] = node['id']; state['queue'] = [item, *queue]
            run.state = state; run.status = 'executando'; run.updated = now
            action = data; revision = run.revision; graph = run.graph
        else:
            finish(state, run.graph, node['id'], port, now)
            state['log'].append({'node': node['id'], 'status': 'concluída', 'port': port, 'at': now})
            run.state = state; run.status = 'pendente'; run.updated = now
    if action is None: return True
    try:
        with DB() as db:
            active = db.get(Workflow, 'main')
            if not active or not active.enabled or active.revision != revision: raise HTTPException(409, 'Fluxo desativado ou alterado')
        if not take_rate('commands', 20): raise HTTPException(429, 'Limite de comandos atingido')
        if node['kind'] == 'notification':
            result = send_notification(action, {'run_id': identifier, 'node_id': node['id'], 'flow_name': active.name, 'revision': revision, 'timestamp': now})
        else:
            result = submit_action(action['device_id'], {'type': action['type'], 'value': action['value']}, f'flow:{identifier}:{node["id"]}', 'workflow:main', adapter, graph['cooldown_seconds'], continuation_prefix=f'flow:{identifier}:')
    except HTTPException as exc: result = {'status': 'bloqueada', 'detail': str(exc.detail)}
    except Exception as exc: result = {'status': 'resultado desconhecido', 'detail': type(exc).__name__}
    with DB.begin() as db:
        run = db.execute(select(WorkflowRun).where(WorkflowRun.id == identifier).with_for_update()).scalar_one()
        state = copy.deepcopy(run.state); state.pop('running', None)
        state['log'].append({'node': node['id'], **result, 'at': now})
        if result['status'] in ('aceito pela Tuya', 'aceito pelo provedor'):
            finish(state, run.graph, node['id'], 'out', now); run.status = 'pendente'
        else: run.status = result['status']
        run.state = state; run.updated = now
    return result['status'] in ('aceito pela Tuya', 'aceito pelo provedor')


def finish(state, graph, identifier, port, now):
    state['done'].append(identifier)
    state['queue'] = [q for q in state['queue'] if q['node'] != identifier]
    for edge in graph['edges']:
        if edge['source'] == identifier and edge['port'] == port and edge['target'] not in state['done'] and not any(q['node'] == edge['target'] for q in state['queue']):
            state['queue'].append({'node': edge['target'], 'at': now})
