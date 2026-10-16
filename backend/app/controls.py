import time
from typing import Literal
from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr, model_validator
from sqlalchemy import select, func
from .db import DB, Device, State, Command, Automation, health, take_rate
from .security import authenticate
from .commands import submit_action, serialize
from .control_profiles import capabilities, ID

router=APIRouter(prefix='/api/v1')

class Action(BaseModel):
    type:Literal['power','temperature','mode','fan','ir_key']
    value:StrictBool|StrictInt|StrictStr

class DeviceSetup(BaseModel):
    id:str=Field(pattern=ID)
    name:str=Field(min_length=1,max_length=100)
    sensing:bool=True
    infrared:bool=False
    virtual:bool=False
    api_family:Literal['iot-03','legacy']='iot-03'
    temperature_code:str=Field(default='va_temperature',pattern=ID)
    temperature_scale:int=Field(default=1,ge=0,le=6)
    humidity_code:str=Field(default='va_humidity',pattern=ID)
    humidity_scale:int=Field(default=0,ge=0,le=6)
    expected_interval:int=Field(default=300,ge=10,le=86400)
    hub_id:str=Field(default='',max_length=128)
    remote_id:str=Field(default='',max_length=128)
    power_enabled:bool=False
    temperature_enabled:bool=False
    status_enabled:bool=False
    temperature_min:int=Field(default=16,ge=10,le=35)
    temperature_max:int=Field(default=30,ge=10,le=35)
    profile:Literal['tuya_ac_v2','tuya_standard_ir']='tuya_ac_v2'
    keys_enabled:bool=False
    @model_validator(mode='after')
    def valid(self):
        import re
        if not self.sensing and not self.infrared:
            raise ValueError('Escolha ao menos uma função para o dispositivo')
        if self.temperature_code==self.humidity_code:
            raise ValueError('Os códigos de temperatura e umidade precisam ser diferentes')
        if self.temperature_min>=self.temperature_max:
            raise ValueError('Intervalo de temperatura inválido')
        for value in (self.hub_id,self.remote_id):
            if value and not re.fullmatch(ID,value):raise ValueError('Identificador Tuya inválido')
        if (self.power_enabled or self.temperature_enabled or self.status_enabled or self.keys_enabled) and (not self.infrared or not self.remote_id):
            raise ValueError('Informe o controle virtual antes de habilitar as capacidades IR')
        if self.profile=='tuya_standard_ir' and (self.power_enabled or self.temperature_enabled or self.status_enabled):
            raise ValueError('O perfil de teclas IR não oferece comandos ou status de ar-condicionado')
        return self

def admin(request):
    if authenticate(request)!='admin':raise HTTPException(403,'Apenas o administrador pode configurar dispositivos')

@router.get('/integrations/devices')
def configured(request:Request):
    authenticate(request)
    with DB() as db:
        return [{'id':d.id,'name':d.name,'config':d.config,'control':capabilities(d)} for d in db.query(Device).order_by(Device.name)]

@router.put('/integrations/devices')
def configure(body:DeviceSetup,request:Request):
    admin(request)
    with DB.begin() as db:
        device=db.execute(select(Device).where(Device.id==body.id).with_for_update()).scalar_one_or_none()
        if not device:
            if db.scalar(select(func.count()).select_from(Device))>=50:raise HTTPException(409,'Limite de 50 dispositivos')
            device=Device(id=body.id,name=body.name,config={});db.add(device)
        cfg={'managed_by_ui':True,'api_family':body.api_family,'expected_interval':body.expected_interval,'virtual':body.virtual,
             'cloud_snapshot_without_timestamp':body.virtual,'properties':{}}
        if body.sensing:
            cfg['properties']={body.temperature_code:{'property':'temperature','scale':body.temperature_scale,'unit':'°C'},body.humidity_code:{'property':'humidity','scale':body.humidity_scale,'unit':'%'}}
        if body.infrared:
            cfg['command']={'kind':'ir','profile':'tuya_ac_v2','infrared_id':body.hub_id or body.id,'remote_id':body.remote_id,
                            'validated':body.power_enabled,'ac':{'validated':body.temperature_enabled,'status_validated':body.status_enabled,
                            'temperature':{'min':body.temperature_min,'max':body.temperature_max},'modes':[],'fan_speeds':[]}}
            if body.profile=='tuya_standard_ir':
                cfg['command']={'kind':'ir','profile':body.profile,'infrared_id':body.hub_id or body.id,'remote_id':body.remote_id,
                                'validated':False,'keys_enabled':body.keys_enabled,'keys_validated':False,'keys':[]}
                prior=device.config.get('command',{})
                if all(prior.get(k)==cfg['command'].get(k) for k in ('profile','infrared_id','remote_id')):
                    for key in ('keys','keys_validated','category_id','remote_index','duplicate_power','physical_tests'):
                        if key in prior:cfg['command'][key]=prior[key]
        previous=device.config
        sensor_changed=previous.get('properties',{})!=cfg['properties'] or previous.get('api_family')!=cfg['api_family']
        old_control=previous.get('command',{})
        new_control=cfg.get('command',{})
        control_changed=any(old_control.get(key)!=new_control.get(key) for key in ('profile','infrared_id','remote_id'))
        device.name,device.config=body.name,cfg
        # Remove stale role values only when a role is explicitly removed.
        for state in db.query(State).filter_by(device_id=body.id):
            if ((not body.sensing or sensor_changed) and state.property in ('temperature','humidity')) or ((not body.infrared or control_changed) and state.property in ('power','target_temperature','ac_mode','fan_speed','last_ir_key')):
                db.delete(state)
        if sensor_changed:
            for rule in db.query(Automation):
                if rule.definition['trigger'].get('device_id')==body.id:
                    rule.runtime={**rule.runtime,'since':None,'last_sample':0,'last_tick':0,'reason':'Configuração do sensor alterada; reiniciando contagem'}
        return {'id':body.id,'control':capabilities(device)}

@router.get('/devices/{device_id}/control')
def control_info(device_id:str,request:Request):
    authenticate(request)
    with DB() as db:
        device=db.get(Device,device_id)
        if not device:raise HTTPException(404,'Dispositivo não encontrado')
        values=[{'property':s.property,'value':s.value,'source':s.source,'observed':s.observed,'unit':s.unit} for s in db.query(State).filter_by(device_id=device_id) if s.property in ('power','target_temperature','ac_mode','fan_speed','last_ir_key')]
        latest=db.query(Command).filter_by(device_id=device_id).order_by(Command.created.desc()).limit(20).all()
        return {'id':device.id,'name':device.name,'capabilities':capabilities(device),'states':values,'commands':[serialize(c) for c in latest],
                'configured':device.config.get('command',{}).get('kind')=='ir',
                'profile':device.config.get('command',{}).get('profile','tuya_ac_v2'),
                'physical_tests':device.config.get('command',{}).get('physical_tests',{})}

@router.post('/devices/{device_id}/control/discover')
def discover_keys(device_id:str,request:Request):
    admin(request)
    if not take_rate('manual_sync',2):raise HTTPException(429,'Aguarde antes de consultar novamente')
    with DB() as db:
        device=db.get(Device,device_id)
        if not device:raise HTTPException(404,'Dispositivo não encontrado')
        cfg=device.config.get('command',{})
        if cfg.get('profile')!='tuya_standard_ir' or not cfg.get('infrared_id') or not cfg.get('remote_id'):
            raise HTTPException(422,'Configure o hub, o controle virtual e o perfil de teclas IR')
        prior_identity=(cfg['infrared_id'],cfg['remote_id'])
    try:result=request.app.state.tuya.read_keys(device)
    except Exception:raise HTTPException(502,'Não foi possível consultar as teclas na Tuya')
    if not isinstance(result,dict) or type(result.get('category_id')) is not int or type(result.get('remote_index')) is not int or not isinstance(result.get('key_list'),list):
        raise HTTPException(502,'Metadados do controle inválidos')
    keys=[{'key':item['key'],'label':str(item.get('key_name') or item['key'])[:100]} for item in result['key_list'] if isinstance(item,dict) and item.get('standard_key') is True and isinstance(item.get('key'),str) and 0<len(item['key'])<=128]
    if not keys:raise HTTPException(422,'Nenhuma tecla padrão disponível nesse controle')
    with DB.begin() as db:
        device=db.execute(select(Device).where(Device.id==device_id).with_for_update()).scalar_one()
        cfg=device.config.get('command',{})
        if cfg.get('profile')!='tuya_standard_ir' or (cfg.get('infrared_id'),cfg.get('remote_id'))!=prior_identity:
            raise HTTPException(409,'Configuração alterada durante a consulta; consulte novamente')
        device.config={**device.config,'command':{**cfg,'keys':keys[:100],'keys_validated':True,'category_id':result['category_id'],
                     'remote_index':result['remote_index'],'duplicate_power':bool(result.get('duplicate_power')),
                     'physical_tests':cfg.get('physical_tests',{}) if cfg.get('remote_index')==result['remote_index'] else {}}}
    return control_info(device_id,request)

@router.post('/devices/{device_id}/control/commands')
def control_command(device_id:str,body:Action,request:Request,idempotency_key:str=Header(min_length=8,max_length=128)):
    actor=authenticate(request,control=True)
    if not take_rate('commands',20):raise HTTPException(429,'Limite de comandos atingido')
    return submit_action(device_id,body.model_dump(),idempotency_key,actor,request.app.state.tuya)

@router.post('/devices/{device_id}/control/status')
def cloud_status(device_id:str,request:Request):
    authenticate(request)
    if not take_rate('manual_sync',2):raise HTTPException(429,'Aguarde antes de consultar novamente')
    with DB() as db:
        device=db.get(Device,device_id)
        if not device:raise HTTPException(404,'Dispositivo não encontrado')
        if not capabilities(device)['cloud_status']:raise HTTPException(422,'Consulta de status IR ainda não habilitada')
    at=time.time()
    try:result=request.app.state.tuya.read_control(device)
    except Exception as exc:
        health('ir_status',{'ok':False,'error':type(exc).__name__})
        raise HTTPException(502,'Não foi possível consultar o controle na Tuya')
    if not isinstance(result,dict):raise HTTPException(502,'Resposta de status inválida')
    mapping={'power':('power',lambda v: {'0':False,'1':True}[str(v)]),'temp':('target_temperature',lambda v:int(v)),
             'mode':('ac_mode',lambda v:int(v)),'wind':('fan_speed',lambda v:int(v))}
    with DB.begin() as db:
        for key,(prop,convert) in mapping.items():
            if key not in result:continue
            try:value=convert(result[key])
            except (ValueError,KeyError,TypeError):continue
            if prop=='target_temperature' and not 10<=value<=40:continue
            state=db.get(State,(device_id,prop))
            if not state or state.observed<=at:
                db.merge(State(device_id=device_id,property=prop,value=value,unit='°C' if prop=='target_temperature' else '',source='estimado',observed=at,received=time.time()))
    return control_info(device_id,request)
