"""Persistent rule evaluator. Runs in the worker; dashboards never trigger rules."""
import math
import time
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import DB, Automation, AutomationRun, Workflow, Device, State, Measurement, health, take_rate
from .security import authenticate
from .controls import Action
from .control_profiles import validate_action
from .commands import submit_action

router=APIRouter(prefix='/api/v1/automations')
ZONE=ZoneInfo('America/Sao_Paulo')

class Trigger(BaseModel):
    kind:Literal['temperature','schedule']='temperature'
    device_id:str=Field(default='',max_length=128)
    operator:Literal['above','below']='above'
    threshold:float=Field(default=27,ge=-50,le=80,allow_inf_nan=False)
    duration_seconds:int=Field(default=300,ge=0,le=86400)
    hysteresis:float=Field(default=.5,ge=0,le=10,allow_inf_nan=False)
    allow_virtual:bool=False
    time:str=Field(default='18:00',pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    weekdays:list[int]=Field(default_factory=lambda:list(range(7)),min_length=1,max_length=7)
    @model_validator(mode='after')
    def check(self):
        if any(type(day) is not int or not 0<=day<=6 for day in self.weekdays):raise ValueError('Dias da semana inválidos')
        if self.kind=='temperature' and not self.device_id:raise ValueError('Selecione o sensor de temperatura')
        return self

class RuleAction(Action):
    device_id:str=Field(min_length=1,max_length=128)

class RuleBody(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    trigger:Trigger
    actions:list[RuleAction]=Field(default_factory=list,max_length=5)
    cooldown_seconds:int=Field(default=300,ge=60,le=86400)
    @model_validator(mode='after')
    def distinct(self):
        ids=[(a.device_id,a.type,a.value if a.type=='ir_key' else None) for a in self.actions]
        if len(ids)!=len(set(ids)):raise ValueError('Não repita o mesmo tipo de comando no mesmo aparelho')
        return self

class Switch(BaseModel):
    enabled:bool


def admin(request):
    if authenticate(request)!='admin':raise HTTPException(403,'Somente o administrador pode alterar automações')


def ready(db,definition):
    trigger=definition['trigger'];issues=[]
    if trigger['kind']=='temperature':
        device=db.get(Device,trigger['device_id'])
        if not device or not any(v.get('property')=='temperature' for v in device.config.get('properties',{}).values()):issues.append('Sensor de temperatura não configurado')
        elif device.config.get('virtual') and not trigger.get('allow_virtual'):issues.append('Sensor virtual: autorize explicitamente o uso de valores simulados')
        elif device.config.get('cloud_snapshot_without_timestamp') and not device.config.get('virtual'):issues.append('O sensor não informa o horário da medição')
    if not definition['actions']:issues.append('Escolha ao menos uma ação')
    for action in definition['actions']:
        target=db.get(Device,action['device_id'])
        if not target:issues.append('Destino da ação ainda não cadastrado');continue
        try:validate_action(target,{'type':action['type'],'value':action['value']})
        except HTTPException as exc:issues.append(target.name+': '+exc.detail)
    return issues


def serialized(db,rule):
    return {'id':rule.id,'name':rule.name,'enabled':rule.enabled,**rule.definition,'runtime':rule.runtime,
            'issues':ready(db,rule.definition),'updated':rule.updated}

@router.get('')
def list_rules(request:Request):
    authenticate(request)
    with DB() as db:return [serialized(db,r) for r in db.query(Automation).order_by(Automation.updated.desc())]

@router.post('',status_code=201)
def create(body:RuleBody,request:Request):
    admin(request)
    with DB.begin() as db:
        if db.query(Automation).count()>=100:raise HTTPException(409,'Limite de 100 regras')
        rule=Automation(name=body.name,enabled=False,definition=body.model_dump(exclude={'name'}),runtime={})
        db.add(rule);db.flush();return serialized(db,rule)

@router.put('/{rule_id}')
def update(rule_id:str,body:RuleBody,request:Request):
    admin(request)
    with DB.begin() as db:
        rule=db.execute(select(Automation).where(Automation.id==rule_id).with_for_update()).scalar_one_or_none()
        if not rule:raise HTTPException(404,'Regra não encontrada')
        # Edits require explicit re-enabling and restart pending duration.
        rule.name,rule.definition,rule.enabled,rule.updated=body.name,body.model_dump(exclude={'name'}),False,time.time()
        rule.runtime={'last_fired':rule.runtime.get('last_fired',0)}
        return serialized(db,rule)

@router.patch('/{rule_id}/enabled')
def enable(rule_id:str,body:Switch,request:Request):
    admin(request)
    with DB.begin() as db:
        rule=db.execute(select(Automation).where(Automation.id==rule_id).with_for_update()).scalar_one_or_none()
        if not rule:raise HTTPException(404,'Regra não encontrada')
        if body.enabled:
            if db.get(Workflow, 'main'):raise HTTPException(409,'Use o editor visual para ativar o fluxo de automações')
            issues=ready(db,rule.definition)
            if issues:raise HTTPException(422,'; '.join(issues))
        if rule.enabled!=body.enabled:
            rule.runtime={'last_fired':rule.runtime.get('last_fired',0)}
        rule.enabled=body.enabled;rule.updated=time.time()
        return serialized(db,rule)

@router.delete('/{rule_id}')
def remove(rule_id:str,request:Request):
    admin(request)
    with DB.begin() as db:
        rule=db.execute(select(Automation).where(Automation.id==rule_id).with_for_update()).scalar_one_or_none()
        if not rule:raise HTTPException(404,'Regra não encontrada')
        db.delete(rule)
    return {'ok':True}

@router.get('/history/runs')
def runs(request:Request,rule_id:str|None=None):
    authenticate(request)
    with DB() as db:
        query=db.query(AutomationRun)
        if rule_id:query=query.filter_by(rule_id=rule_id)
        return [{'id':r.id,'rule_id':r.rule_id,'status':r.status,'created':r.created,'results':r.results,'definition':r.definition} for r in query.order_by(AutomationRun.created.desc()).limit(100)]

@router.post('/{rule_id}/preview')
def preview(rule_id:str,request:Request):
    admin(request)
    with DB() as db:
        rule=db.get(Automation,rule_id)
        if not rule:raise HTTPException(404,'Regra não encontrada')
        temporary=Automation(id=rule.id,name=rule.name,enabled=True,definition=rule.definition,runtime=dict(rule.runtime))
        due,reason=evaluate(db,temporary,time.time())
        issues=ready(db,rule.definition)
        return {'would_fire':bool(due) and not issues,'reason':reason,'issues':issues,'sends_commands':False}


def evaluate(db,rule,now):
    runtime=dict(rule.runtime or {});trigger=rule.definition['trigger']
    gap=now-runtime.get('last_tick',0)>20
    runtime['last_tick']=now
    due=None
    if trigger['kind']=='schedule':
        local=datetime.fromtimestamp(now,ZONE)
        occurrence=local.strftime('%Y-%m-%dT%H:%M')
        if local.weekday() not in trigger['weekdays'] or local.strftime('%H:%M')!=trigger['time']:
            reason='Aguardando horário programado'
        elif runtime.get('last_schedule')==occurrence:
            reason='Horário já processado'
        elif now-runtime.get('last_fired',0)<rule.definition['cooldown_seconds']:
            reason='Aguardando intervalo mínimo'
        else:
            due=occurrence;reason='Horário atingido';runtime['last_schedule']=occurrence
    else:
        device=db.get(Device,trigger['device_id']);state=db.get(State,(trigger['device_id'],trigger.get('property','temperature')))
        max_age=device.config.get('expected_interval',300)*3 if device else 0
        online=db.get(State,(trigger['device_id'],'online'))
        offline=online and online.value is False and now-online.observed<max_age
        unknown_time=state and not state.time_known and not (device and device.config.get('virtual') and trigger.get('allow_virtual'))
        if not device or not state or state.source!='reportado' or unknown_time or not isinstance(state.value,(int,float)) or isinstance(state.value,bool) or not math.isfinite(state.value) or not -5<=now-state.observed<=max_age or offline:
            runtime['since']=None;runtime['last_sample']=0;reason='Aguardando medição válida e atualizada'
        else:
            above=trigger['operator']=='above';limit=trigger['threshold'];h=trigger['hysteresis']
            if gap:
                runtime['since']=None;runtime['last_sample']=state.observed
                samples=[(now,state.value)]
            else:
                rows=db.execute(select(Measurement).where(Measurement.device_id==device.id,Measurement.property==trigger.get('property','temperature'),Measurement.observed>runtime.get('last_sample',0),Measurement.observed<=now,Measurement.observed>=now-max_age).order_by(Measurement.observed,Measurement.id).limit(2001)).scalars().all()
                rows=[r for r in rows if r.time_known or (device.config.get('virtual') and trigger.get('allow_virtual'))]
                samples=[(r.observed,r.value) for r in rows]
                if len(samples)>2000:
                    runtime['since']=None;samples=[(now,state.value)]
            for observed,value in samples:
                if type(value) not in (int,float) or not math.isfinite(value):runtime['since']=None;continue
                if observed-runtime.get('last_sample',observed)>max_age:runtime['since']=None
                if (above and value<=limit-h) or (not above and value>=limit+h):runtime['latched']=False
                matching=value>limit if above else value<limit
                if matching:
                    if runtime.get('since') is None:runtime['since']=max(observed,now) if gap else observed
                else:runtime['since']=None
                runtime['last_sample']=max(runtime.get('last_sample',0),observed)
            matching=state.value>limit if above else state.value<limit
            if not matching:
                runtime['since']=None;reason='Aguardando condição de temperatura'
            elif runtime.get('latched'):
                reason='Executada; aguardando a temperatura sair da faixa'
            elif runtime.get('since') is None:
                runtime['since']=now;reason='Iniciando contagem da condição'
            elif now-runtime['since']<trigger['duration_seconds']:
                reason='Contando duração da condição'
            elif now-runtime.get('last_fired',0)<rule.definition['cooldown_seconds']:
                reason='Aguardando intervalo mínimo'
            else:
                due='temperature:'+str(runtime['since']);runtime['latched']=True;reason='Condição confirmada'
    runtime['reason']=reason
    if due:runtime['last_fired']=now
    rule.runtime=runtime
    return due,reason


def tick(adapter,now=None):
    now=time.time() if now is None else now
    with DB() as db:
        if db.get(Workflow, 'main'):return
        ids=[r.id for r in db.query(Automation).filter_by(enabled=True)]
    for identifier in ids:
        run_id=None
        try:
            with DB.begin() as db:
                rule=db.execute(select(Automation).where(Automation.id==identifier).with_for_update(skip_locked=True)).scalar_one_or_none()
                if not rule or not rule.enabled:continue
                issues=ready(db,rule.definition)
                if issues:
                    rule.runtime={**rule.runtime,'since':None,'last_tick':now,'reason':'; '.join(issues)};continue
                due,_=evaluate(db,rule,now)
                if not due:continue
                run=AutomationRun(rule_id=rule.id,occurrence=due,definition={'name':rule.name,**rule.definition},created=now)
                db.add(run);db.flush();run_id=run.id;definition=run.definition
        except IntegrityError:
            continue
        if run_id:
            results=[];status='concluída'
            for index,action in enumerate(definition['actions']):
                try:
                    # Re-check enabled state immediately before each external action.
                    with DB() as db:
                        active=db.get(Automation,identifier)
                        if not active or not active.enabled or active.definition!={k:v for k,v in definition.items() if k!='name'}:
                            raise HTTPException(409,'Regra desativada ou alterada durante a execução')
                    if not take_rate('commands',20):raise HTTPException(429,'Limite de comandos atingido')
                    result=submit_action(action['device_id'],{'type':action['type'],'value':action['value']},f'auto:{run_id}:{index}','automation:'+identifier,adapter,definition['cooldown_seconds'],continuation_prefix=f'auto:{run_id}:')
                    results.append(result)
                    if result['status']!='aceito pela Tuya':
                        status='resultado desconhecido' if result['status']=='resultado desconhecido' else 'falhou';break
                except HTTPException as exc:
                    results.append({'device_id':action['device_id'],'status':'bloqueada','detail':exc.detail});status='bloqueada';break
                except Exception as exc:
                    results.append({'status':'resultado desconhecido','error':type(exc).__name__});status='resultado desconhecido';break
            with DB.begin() as db:
                run=db.get(AutomationRun,run_id);run.status,run.results=status,results
    health('automations',{'alive':True,'at':now,'enabled':len(ids)})
