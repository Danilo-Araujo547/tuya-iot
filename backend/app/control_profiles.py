"""Capability contract shared by manual control and the automation engine."""
import re
from fastapi import HTTPException

ID = r'^[A-Za-z0-9_-]{1,128}$'

def capabilities(device):
    cfg=device.config.get('command',{})
    ac=cfg.get('ac',{})
    address=bool(re.fullmatch(ID,cfg.get('infrared_id','')) and re.fullmatch(ID,cfg.get('remote_id','')))
    temperature=ac.get('temperature')
    generic=cfg.get('profile')=='tuya_standard_ir'
    return {'power':bool(not generic and cfg.get('validated') and (cfg.get('profile')!='tuya_ac_v2' or address)),
            'temperature':temperature if address and ac.get('validated') and isinstance(temperature,dict) else None,
            'modes':ac.get('modes',[]) if address and ac.get('validated') else [],
            'fan_speeds':ac.get('fan_speeds',[]) if address and ac.get('validated') else [],
            'cloud_status':bool(not generic and address and ac.get('status_validated')),
            'keys':cfg.get('keys',[]) if generic and address and cfg.get('keys_validated') and cfg.get('keys_enabled') else []}


def validate_action(device,action):
    caps=capabilities(device);kind=action.get('type');value=action.get('value')
    if kind=='power' and isinstance(value,bool) and caps['power']:
        return
    if kind=='temperature' and type(value) is int and caps['temperature']:
        bounds=caps['temperature']
        if bounds['min']<=value<=bounds['max']:
            return
    if kind=='mode' and type(value) is int and value in caps['modes']:
        return
    if kind=='fan' and type(value) is int and value in caps['fan_speeds']:
        return
    if kind=='ir_key' and isinstance(value,str) and value in {item['key'] for item in caps['keys']}:
        return
    raise HTTPException(422,'Comando ou capacidade ainda não validado para este aparelho')
