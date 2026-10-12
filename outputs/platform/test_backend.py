import shutil
import sys
from pathlib import Path
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parent))
from backend import create_app,finance,instant
from store import connect

@pytest.fixture
def client(tmp_path):
    path=tmp_path/'test.sqlite3';shutil.copyfile(Path(__file__).with_name('hoppr.sqlite3'),path)
    with TestClient(create_app(path,background=False)) as c:yield c,path

def auth(c,app,account=None):
    response=c.post('/v2/auth/demo',json={'app':app,'account_id':account});assert response.status_code==200
    return {'Authorization':'Bearer '+response.json()['token']}

def match(c,h,flight=None,**kwargs):
    flight=flight or c.get('/v2/flights?airport=DEL').json()['items'][0]
    payload={'flight_id':flight['id'],'destination':'DEL-A01',**kwargs}
    response=c.post('/v2/match',json=payload,headers=h);assert response.status_code==200,response.text
    return response.json()

def test_three_app_login_and_roles(client):
    c,_=client
    assert c.get('/v2/me').status_code==401
    rh=auth(c,'rider');assert c.get('/v2/me',headers=rh).json()['account']['email']=='demo@hoppr.app'
    dh=auth(c,'driver');assert c.get('/v2/ops/summary',headers=dh).status_code==401
    sh=auth(c,'ops','O3');assert c.get('/v2/ops/table/payments',headers=sh).status_code==403
    assert c.post('/v2/ops/action',headers=sh,json={'entity_id':'D001','action':'approve'}).status_code==403

def test_booking_price_lock_eta_private_and_refund(client):
    c,path=client;h=auth(c,'rider');q=match(c,h,ride_type='private')
    b=q['booking'];locked=c.post('/v2/book',headers=h,json={'booking_id':b['id'],'version':b['version']}).json();total=locked['total']
    oh=auth(c,'ops');eta=(instant(b['ready_time'])+timedelta(minutes=70)).isoformat()
    assert c.post('/v2/ops/action',headers=oh,json={'entity_id':b['flight_id'],'action':'eta','value':eta}).status_code==200
    updated=c.get('/v2/ride/'+b['id'],headers=h).json();assert updated['total']==total
    assert len(updated['pool']['members'])==1
    assert c.get('/v2/notifications',headers=h).json()
    assert c.post('/v2/cancel',headers=h,json={'entity_id':b['id'],'action':'cancel'}).status_code==200
    assert c.post('/v2/cancel',headers=h,json={'entity_id':b['id'],'action':'cancel'}).json()['idempotent']
    with connect(path) as db:assert finance(db)['reconciled']

def test_real_match_and_driver_otp_stages(client):
    c,path=client;h1=auth(c,'rider');h2=auth(c,'rider','R0007');q1=match(c,h1);q2=match(c,h2)
    assert len(q2['pool']['members'])==2
    q1=c.get('/v2/ride/'+q1['booking']['id'],headers=h1).json()
    for h,q in [(h1,q1),(h2,q2)]:
        assert c.post('/v2/book',headers=h,json={'booking_id':q['booking']['id'],'version':q['booking']['version']}).status_code==200
    dh=auth(c,'driver',q2['pool']['driver_id']);pid=q2['pool']['id']
    for stage in ['accepted','en_route','arrived']:assert c.post('/v2/driver/step',headers=dh,json={'pool_id':pid,'step':stage}).status_code==200
    assert c.post('/v2/driver/step',headers=dh,json={'pool_id':pid,'step':'picked_up','codes':{}}).status_code==422
    codes={q['booking']['id']:q['booking']['pickup_code'] for q in [q1,q2]}
    for stage in ['picked_up','completed']:assert c.post('/v2/driver/step',headers=dh,json={'pool_id':pid,'step':stage,'codes':codes}).status_code==200
    assert c.get('/v2/ride/'+q1['booking']['id'],headers=h1).json()['booking']['status']=='completed'
    before=c.get('/v2/ride/'+q1['booking']['id'],headers=h1).json()
    assert c.post('/v2/tip',headers=h1,json={'entity_id':q1['booking']['id'],'action':'tip','value':'2000'}).status_code==200
    after=c.get('/v2/ride/'+q1['booking']['id'],headers=h1).json()
    assert after['total']==before['total']+2000 and after['locked_total']==before['locked_total']
    assert c.post('/v2/tip',headers=h1,json={'entity_id':q1['booking']['id'],'action':'tip','value':'2000'}).json()['already_tipped']
    assert c.post('/v2/rating',headers=dh,json={'entity_id':q1['booking']['id'],'action':'rider','value':'5'}).status_code==200
    with connect(path) as db:
        assert finance(db)['reconciled']
        assert finance(db,driver_id=q2['pool']['driver_id'])['driver_payout']>0

def test_wrong_account_duplicate_and_stale_quote(client):
    c,_=client;h=auth(c,'rider');q=match(c,h);other=auth(c,'rider','R0007')
    assert c.get('/v2/ride/'+q['booking']['id'],headers=other).status_code==403
    assert c.post('/v2/match',headers=h,json={'flight_id':q['booking']['flight_id'],'destination':'DEL-A01'}).status_code==409
    assert c.post('/v2/book',headers=h,json={'booking_id':q['booking']['id'],'version':0}).status_code==409

def test_ops_csv_sort_health_finance(client):
    c,_=client;h=auth(c,'ops')
    assert c.get('/v2/ops/table/flights?page=1&size=3&q=DEL&sort=estimated&descending=true',headers=h).json()['total']>3
    csv=c.get('/v2/ops/export/drivers',headers=h);assert csv.status_code==200 and 'text/csv' in csv.headers['content-type']
    summary=c.get('/v2/ops/summary',headers=h).json();assert summary['finance']['reconciled'];assert len(summary['history'])==14
    assert c.get('/v2/health').json()['live_api_verified'] is False

def test_equipment_is_not_falsely_promised(client):
    c,_=client;h=auth(c,'rider');f=c.get('/v2/flights').json()['items'][0]
    assert c.post('/v2/match',headers=h,json={'flight_id':f['id'],'destination':'DEL-A01','child_seat':True}).status_code==409

def test_support_and_preference_persistence(client):
    c,_=client;h=auth(c,'rider')
    assert c.post('/v2/support',headers=h,json={'entity_id':'','action':'Pickup','message':'Where do I meet my driver?'}).status_code==200
    c.post('/v2/account',headers=h,json={'entity_id':'','action':'language','value':'hi'})
    assert c.get('/v2/me',headers=h).json()['account']['language']=='hi'

def test_pricing_changes_new_quotes_preserves_locks_and_audits(client):
    c,_=client;h=auth(c,'rider');oh=auth(c,'ops');q=match(c,h)
    c.post('/v2/book',headers=h,json={'booking_id':q['booking']['id'],'version':q['booking']['version']})
    rules={'airport':'DEL','base':200,'per_km':50,'night_multiplier':1.25,'detour':1.1,'service_fee':22,'driver_share':.75}
    import json
    assert c.post('/v2/ops/action',headers=oh,json={'entity_id':'DEL','action':'pricing','value':json.dumps(rules)}).status_code==200
    assert c.get('/v2/ride/'+q['booking']['id'],headers=h).json()['total']==q['total']
    new=match(c,auth(c,'rider','R0007'),ride_type='private')
    assert new['booking']['pricing_snapshot']['base']==200
    assert new['booking']['locked_transport']%1000==0
    assert new['service_fee']==2200
    assert c.get('/v2/ops/table/audit?q=pricing',headers=oh).json()['total']>0
    rules['per_km']=-1
    assert c.post('/v2/ops/action',headers=oh,json={'entity_id':'DEL','action':'pricing','value':json.dumps(rules)}).status_code==422

def test_demo_incident_is_visible_to_ops(client):
    c,_=client;h=auth(c,'rider');q=match(c,h)
    incident=c.post('/v2/incident',headers=h,json={'entity_id':q['pool']['id'],'action':'sos'}).json()
    oh=auth(c,'ops');assert c.get('/v2/ops/table/incidents?q='+incident['id'],headers=oh).json()['total']==1
