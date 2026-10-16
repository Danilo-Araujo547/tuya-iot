import time
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import DB, Device, Command, State
from .control_profiles import validate_action
from .tuya import Rejected


def serialize(command):
    result={key:getattr(command,key) for key in ('id','device_id','power','status','response','created','updated')}
    result['action']=command.payload or {'type':'power','value':command.power}
    return result


def submit(device_id,power,key,actor,adapter):
    return submit_action(device_id,{'type':'power','value':power},key,actor,adapter)


def submit_action(device_id,action,key,actor,adapter,minimum_interval=0,continuation_prefix=None):
    with DB() as db:
        prior=db.query(Command).filter_by(actor=actor,key=key).first()
        if prior:
            if prior.device_id!=device_id or (prior.payload or {'type':'power','value':prior.power})!=action:
                raise HTTPException(409,'Chave de idempotência usada para outro comando')
            return serialize(prior)
        device=db.execute(select(Device).where(Device.id==device_id).with_for_update()).scalar_one_or_none()
        if not device:
            raise HTTPException(404,'Dispositivo não encontrado')
        validate_action(device,action)
        # Recheck after the device lock: another request may have just committed.
        prior=db.query(Command).filter_by(actor=actor,key=key).first()
        if prior:
            if prior.device_id!=device_id or prior.payload!=action:
                raise HTTPException(409,'Chave de idempotência usada para outro comando')
            return serialize(prior)
        latest=db.query(Command).filter_by(device_id=device_id).order_by(Command.created.desc()).first()
        now=time.time()
        if latest and latest.status=='solicitado':
            raise HTTPException(409,'Já existe um comando em andamento para este aparelho')
        continuation=latest and continuation_prefix and latest.actor==actor and latest.key.startswith(continuation_prefix)
        if latest and minimum_interval and now-latest.created<minimum_interval and not continuation:
            raise HTTPException(409,'Intervalo de proteção do aparelho ainda não terminou')
        command=Command(device_id=device_id,actor=actor,key=key,power=action['value'] if action['type']=='power' else None,payload=action)
        db.add(command)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return submit_action(device_id,action,key,actor,adapter,minimum_interval,continuation_prefix)
        command_id=command.id
    status,result='aceito pela Tuya',None
    try:
        accepted=adapter.command(device,action['value']) if action['type']=='power' else adapter.control(device,action)
        if accepted is False:
            raise Rejected('command_not_accepted')
        result={'result':accepted}
    except Rejected as exc:
        status,result='falhou',{'code':exc.code}
    except Exception as exc:
        status,result='resultado desconhecido',{'error':type(exc).__name__}
    with DB.begin() as db:
        command=db.get(Command,command_id)
        command.status,command.response,command.updated=status,result,time.time()
        if status=='aceito pela Tuya':
            prop={'temperature':'target_temperature','mode':'ac_mode','fan':'fan_speed','ir_key':'last_ir_key'}.get(action['type'],'power')
            state=db.get(State,(device_id,prop))
            if not state or state.observed<=command.created:
                db.merge(State(device_id=device_id,property=prop,value=action['value'],unit='°C' if prop=='target_temperature' else '',observed=command.created,received=time.time(),source='estimado'))
        return serialize(command)
