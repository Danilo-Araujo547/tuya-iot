import time
from datetime import datetime, timezone
from app.db import DB, Device, Measurement
from app.connectivity import offline_intervals


def record(db,at,value,prop='online'):
    db.add(Measurement(device_id='sensor',event_id=str(at)+prop,property=prop,
                       value=value,unit='',observed=at,received=at))


def test_loss_before_window_and_repeated_offline_merge():
    with DB.begin() as db:
        record(db,900,False)
        record(db,1200,False)
        record(db,1500,True)
    with DB() as db:
        assert offline_intervals(db,db.get(Device,'sensor'),1000,2000)==[{'start':1000,'end':1500}]


def test_expired_offline_does_not_fill_unknown_time():
    with DB.begin() as db:
        record(db,1000,False)
        record(db,2500,False)
    with DB() as db:
        assert offline_intervals(db,db.get(Device,'sensor'),1000,4000)==[
            {'start':1000,'end':1900},{'start':2500,'end':3400}]


def test_history_exposes_outages_and_excludes_cached_offline_values(logged):
    base=int(time.time()//3600)*3600-7200
    with DB.begin() as db:
        record(db,base+100,True)
        record(db,base+200,20,'temperature')
        record(db,base+300,False)
        record(db,base+400,99,'temperature')
        record(db,base+600,True)
        record(db,base+700,22,'temperature')
    params={'property':'temperature','start':datetime.fromtimestamp(base,timezone.utc).isoformat(),
            'end':datetime.fromtimestamp(base+3600,timezone.utc).isoformat(),'aggregation':'hour'}
    result=logged.get('/api/v1/devices/sensor/history',params=params)
    assert result.status_code==200
    assert result.json()['offline_intervals']==[{'start':base+300,'end':base+600}]
    point=result.json()['points'][0]
    assert point['value']==21 and point['min']==20 and point['max']==22 and point['count']==2
    params['aggregation']='raw'
    raw=logged.get('/api/v1/devices/sensor/history',params=params).json()
    assert len(raw['points'])==3 # Audit history remains intact.
    assert raw['offline_intervals']==result.json()['offline_intervals']


def test_no_connection_reports_does_not_invent_losses():
    with DB() as db:
        assert offline_intervals(db,db.get(Device,'sensor'),0,3000)==[]
