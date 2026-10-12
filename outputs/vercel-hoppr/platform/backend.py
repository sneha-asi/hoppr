"""Hoppr v2: three demo apps, one relational store. No real auth/payment/dispatch."""
import asyncio
import csv
import io
import json
import os
import secrets
import sqlite3
import sys
import time
from collections import Counter,defaultdict
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from decimal import Decimal,ROUND_FLOOR
from pathlib import Path

from fastapi import FastAPI,HTTPException,Header,Request,Query
from fastapi.responses import FileResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import connect,initialize,get,rows,put,RELATIONS
from matcher import Rider,match_riders,quote_fare,round_rs10
from flight_ingest import AeroDataBoxProvider,AirportScraper,fetch_first_success,ProviderError

ROOT=Path(__file__).parent
ROLE_MODULES={'admin':list(RELATIONS),'ops_lead':['airports','flights','flight_updates','pools','bookings','riders','drivers','cabs','incidents','tickets','audit','notifications','demand_requests'],'support':['riders','tickets','incidents','bookings','pools','notifications','audit'],'finance':['payments','wallet_entries','drivers','pools','bookings','promos','passes','referrals','audit']}
ACTIVE={'offered','accepted','en_route','arrived','picked_up'}
def instant(s):return datetime.fromisoformat(s)
def iso():return datetime.now(timezone.utc).isoformat()
def money(d):return int((Decimal(str(d))*100).quantize(Decimal('1')))
def rid(prefix):return prefix+'-'+secrets.token_hex(6)

def tariff(db,airport):
    hub=get(db,'airports',airport)
    base={'base':hub['base_fare'],'per_km':hub['per_km'],'night_multiplier':1.2,'detour':1.15,'service_fee':19,'driver_share':.8}
    saved=db.execute('SELECT value FROM metadata WHERE key=?',('pricing:'+airport,)).fetchone()
    if saved:base.update(json.loads(saved[0]))
    return base

class Login(BaseModel):
    app:str;account_id:str|None=None
class Match(BaseModel):
    flight_id:str;destination:str;party:int=Field(1,ge=1,le=4);bags:int=Field(0,ge=0,le=4);max_wait:int=Field(30,ge=15,le=45);women_only:bool=False;ride_type:str='pool';quiet:bool=False;accessibility:bool=False;child_seat:bool=False
class Booking(BaseModel):
    booking_id:str;method:str='upi';promo:str='';version:int
class Step(BaseModel):
    pool_id:str;step:str;codes:dict[str,str]=Field(default_factory=dict);reason:str=''
class Mutation(BaseModel):
    entity_id:str;action:str;value:str='';message:str=''

def finance(db,driver_id=None,rider_id=None):
    bs={b['id']:b for b in rows(db,'bookings')}
    payments=[p for p in rows(db,'payments') if (not driver_id or bs[p['booking_id']]['driver_id']==driver_id) and (not rider_id or bs[p['booking_id']]['rider_id']==rider_id)]
    dates=defaultdict(lambda:{'collected':0,'driver_payout':0,'platform_fee':0,'tax':0,'refunds':0,'tips':0})
    for p in payments:
        d=dates[p['date']];d['collected']+=p['net'];d['driver_payout']+=p['driver_payout'];d['platform_fee']+=p['platform_fee'];d['tax']+=p['tax'];d['refunds']+=p['refund'];d['tips']+=p.get('tip',0)
    totals={k:sum(d[k] for d in dates.values()) for k in ['collected','driver_payout','platform_fee','tax','refunds','tips']}
    totals['reconciled']=totals['collected']==totals['driver_payout']+totals['platform_fee']+totals['tax']
    totals['by_day']=[dict(date=d,**v) for d,v in sorted(dates.items(),reverse=True)];return totals

def full_pool(db,p):
    p=dict(p);p['members']=[get(db,'bookings',b) for b in p['booking_ids'] if get(db,'bookings',b)['status']!='cancelled']
    for b in p['members']:
        r=get(db,'riders',b['rider_id']);b['first_name']=r['first_name'];b['verified_demo']=r['verified'];b['rating']=r['rating']
        airport=get(db,'airports',p['airport_id']);b['destination_name']=next((a['name'] for a in airport['dropoff_areas'] if a['id']==b['destination']),b['destination'])
    p['driver']=get(db,'drivers',p['driver_id']) if p.get('driver_id') else None
    p['cab']=get(db,'cabs',p['cab_id']) if p.get('cab_id') else None
    return p

def candidate(db,b):
    f=get(db,'flights',b['flight_id']);h=get(db,'airports',f['airport_id']);a=next(a for a in h['dropoff_areas'] if a['id']==b['destination']);r=get(db,'riders',b['rider_id'])
    ready=instant(f['estimated'])+timedelta(minutes=22 if b['bags'] else 12)
    rule=tariff(db,f['airport_id']);solo=(Decimal(str(rule['base']))+Decimal(str(rule['per_km']))*a['road_km'])*(Decimal(str(rule['night_multiplier'])) if ready.hour>=22 or ready.hour<6 else 1)
    return Rider(b['id'],ready,b['max_wait'],a['lat'],a['lng'],r['gender'],b['party'],b['bags'],b['women_only'],solo,f['id'])

def notify(db,audience,entity,text):
    put(db,'notifications',{'id':rid('N'),'audience':audience,'entity_id':entity,'text':text,'at':iso(),'source':'demo'})

def rematch(db,airport,terminal,only_ids=None):
    allbs=rows(db,'bookings'); flights={f['id']:f for f in rows(db,'flights')};bs=[]
    for b in allbs:
        p=get(db,'pools',b['pool_id']);f=flights[b['flight_id']]
        if b['status'] not in ('cancelled','completed') and p['status'] in ('matching','offered') and f['airport_id']==airport and f['terminal']==terminal and (only_ids is None or b['id'] in only_ids):bs.append(b)
    if not bs:return []
    oldpools={b['pool_id'] for b in bs};poolr=[candidate(db,b) for b in bs if b['ride_type']=='pool'];private=[(candidate(db,b),) for b in bs if b['ride_type']=='private'];groups=(*match_riders(poolr),*private);lookup={b['id']:b for b in bs};created=[]
    fleet=[d for d in rows(db,'drivers') if d['airport_id']==airport and d['status']=='approved' and d['online']]
    for pid in oldpools:
        p=get(db,'pools',pid);p['status']='superseded';put(db,'pools',p)
    for group in groups:
        pickup=max(r.ready_time for r in group);h=get(db,'airports',airport);areas={a['id']:a for a in h['dropoff_areas']};duration=max(areas[lookup[r.id]['destination']]['drive_min'] for r in group)+5*(len(group)-1);end=pickup+timedelta(minutes=duration)
        busy={p['driver_id'] for p in rows(db,'pools') if p['status'] in ACTIVE and instant(p['pickup'])<end+timedelta(minutes=15) and instant(p['end'])+timedelta(minutes=15)>pickup}
        d=next((d for d in fleet if d['id'] not in busy),None);cab=next((c for c in rows(db,'cabs') if d and c['driver_id']==d['id']),None)
        p={'id':rid('P'),'airport_id':airport,'terminal':terminal,'driver_id':d['id'] if d else None,'cab_id':cab['id'] if cab else None,'booking_ids':[r.id for r in group],'pickup':pickup.isoformat(),'end':end.isoformat(),'date':pickup.date().isoformat(),'status':'offered' if d else 'matching','seats':sum(r.party_size for r in group),'bags':sum(r.large_bags for r in group),'road_km':max(areas[lookup[r.id]['destination']]['road_km'] for r in group),'events':[{'at':iso(),'text':'Pool recomputed; booked prices preserved'}]}
        put(db,'pools',p);q=quote_fare(group);rule=tariff(db,airport)
        price_per_seat=round_rs10(max(r.solo_fare for r in group)*Decimal(str(rule['detour'] if len(group)>1 else 1))/sum(r.party_size for r in group))
        for r in group:
            b=lookup[r.id];b.update(pool_id=p['id'],driver_id=p['driver_id'],cab_id=p['cab_id'],ready_time=r.ready_time.isoformat(),pickup=p['pickup'],solo_fare=money(r.solo_fare),version=b.get('version',0)+1)
            if b['status']!='booked':
                capped_per_seat=(min(r.solo_fare,Decimal('2500'))/b['party']/10).quantize(Decimal('1'),rounding=ROUND_FLOOR)*10
                b['locked_transport']=money(min(price_per_seat,capped_per_seat)*b['party'])
                b['pricing_snapshot']=rule
            put(db,'bookings',b)
        if d:notify(db,'driver:'+d['id'],p['id'],'New pool offer or pickup re-plan. Review before accepting.')
        created.append(p['id'])
    return created

def update_eta(db,fid,new_eta):
    f=get(db,'flights',fid)
    if not f:raise HTTPException(404,'Flight not found')
    previous=f['estimated'];f['estimated']=instant(new_eta).isoformat();f['delay_min']=round((instant(new_eta)-instant(f['scheduled'])).total_seconds()/60);f['status']='delayed' if f['delay_min']>0 else 'scheduled';put(db,'flights',f)
    put(db,'flight_updates',{'id':rid('U'),'flight_id':fid,'observed_at':iso(),'estimated':f['estimated'],'reason':'Demo ETA simulation'})
    affected={b['pool_id'] for b in rows(db,'bookings') if b['flight_id']==fid and b['status'] not in ('completed','cancelled')};ids={b['id'] for b in rows(db,'bookings') if b['pool_id'] in affected}
    old_drivers={get(db,'pools',pid).get('driver_id') for pid in affected}
    eligible={b['id'] for b in rows(db,'bookings') if b['id'] in ids and get(db,'pools',b['pool_id'])['status'] in ('matching','offered')}
    if eligible:rematch(db,f['airport_id'],f['terminal'],eligible)
    for driver in old_drivers:
        if driver:notify(db,'driver:'+driver,fid,'Flight ETA changed. A queued offer may have been withdrawn or re-planned; refresh your offers before accepting.')
    for b in rows(db,'bookings'):
        if b['id'] in ids:
            text=f'Your flight now lands {instant(new_eta).astimezone(timezone(timedelta(hours=5,minutes=30))):%I:%M %p}, we re-matched your pool' if b['id'] in eligible else 'Flight ETA changed. Trip is dispatched; contact demo support to coordinate.'
            notify(db,'rider:'+b['rider_id'],b['id'],text)
            if b.get('driver_id'):notify(db,'driver:'+b['driver_id'],b['pool_id'],'Flight ETA changed. Review the current pickup plan; dispatched trips require coordination.')
    notify(db,'ops',fid,f'{f["flight_no"]}: ETA changed from {previous} to {new_eta}')
    return list(ids)

def quote(db,b):
    p=full_pool(db,get(db,'pools',b['pool_id']));transport=b['locked_transport'];fee=money(b.get('pricing_snapshot',{}).get('service_fee',19))*b['party'];tax=(transport+fee+10)//20
    payment=next((x for x in rows(db,'payments') if x['booking_id']==b['id']),None)
    rule=b.get('pricing_snapshot',tariff(db,p['airport_id']));hub=get(db,'airports',p['airport_id']);area=next(a for a in hub['dropoff_areas'] if a['id']==b['destination'])
    day=money(rule['base']+rule['per_km']*area['road_km']);details={'base':money(rule['base']),'distance_component':money(rule['per_km']*area['road_km']),'night_surcharge':max(0,b['solo_fare']-day),'detour_multiplier':rule['detour'] if len(p['members'])>1 else 1,'road_km':area['road_km'],'driver_share':rule['driver_share']}
    return {'booking':b,'pool':p,'transport':transport,'service_fee':fee,'tax':tax,'total':payment['gross'] if payment else transport+fee+tax,'locked_total':payment['gross']-payment.get('tip',0) if payment else transport+fee+tax,'per_seat':transport//b['party'],'solo':b['solo_fare'],'savings':max(0,b['solo_fare']-transport),'payment':payment,'tariff_inputs':details,'pickup_point':next(x for x in hub['pickup_points'] if x['terminal']==p['terminal'])}

def create_app(db_path=None,background=True):
    path=Path(db_path or os.environ.get('HOPPR_V2_DB',ROOT/'hoppr.sqlite3'))
    health={a:{'source':'demo','last_success_at':None,'verified_live':False} for a in ['DEL','BOM','BLR']};cache={};limits=defaultdict(list)
    class SharedDemo:
        name='demo'
        def fetch(self,airport):
            with connect(path) as db:return [f for f in rows(db,'flights') if f['airport_id']==airport and f['date']=='2026-10-09']
    async def tick():
        providers=[SharedDemo()] if os.getenv('AIRPOOL_OFFLINE','1')!='0' else [AeroDataBoxProvider(),AirportScraper(),SharedDemo()]
        for airport in health:
            try:
                feed,source=await asyncio.to_thread(fetch_first_success,airport,providers,True)
                with connect(path) as db:
                    for f in feed:
                        existing=get(db,'flights',f['id'])
                        if existing and instant(existing['estimated'])!=instant(f['estimated']):update_eta(db,f['id'],f['estimated'])
                        elif not existing:
                            f.update(airport_id=airport,date=instant(f['scheduled']).date().isoformat(),visible=True,baggage_belt='To confirm');put(db,'flights',f)
                    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('health:'+airport,json.dumps({'source':source,'last_success_at':iso(),'verified_live':False})))
                health[airport]={'source':source,'last_success_at':iso(),'verified_live':False}
            except ProviderError:health[airport]['error']='all_providers_failed'
            except Exception as e:
                from flight_ingest import log_event
                import logging
                log_event(logging.ERROR,'ingest_failure',airport=airport,error_type=type(e).__name__,error_code='v2_ingest_failed')
        cache.clear()
    async def loop():
        while True:
            await tick();await asyncio.sleep(30)
    @asynccontextmanager
    async def lifespan(app):
        if not path.exists():raise RuntimeError('Generate and validate platform demo data first')
        with connect(path) as db:initialize(db)
        task=asyncio.create_task(loop()) if background else None
        yield
        if task:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
    app=FastAPI(title='Hoppr three-app demo',lifespan=lifespan)
    def session(authorization,expected=None):
        token=(authorization or '').removeprefix('Bearer ')
        # Hosted synthetic demo only: account selection is intentionally public.
        # Validate the account and derive roles from seed rows, never token input.
        # A portable selector avoids instance-local SQLite login sessions.
        if token.startswith('hoppr-demo-v1:'):
            parts=token.split(':')
            if len(parts)!=3:raise HTTPException(401,'Choose a demo account for this app')
            _,kind,account=parts
            table={'rider':'riders','driver':'drivers','ops':'ops_users'}.get(kind)
            if not table or expected and kind!=expected:raise HTTPException(401,'Choose a demo account for this app')
            with connect(path) as db:row=get(db,table,account)
            if not row:raise HTTPException(401,'Choose a demo account for this app')
            return {'app':kind,'account_id':account,'role':row.get('role')}
        with connect(path) as db:s=db.execute('SELECT * FROM sessions WHERE token=?',(token,)).fetchone()
        if not s or expected and s['app']!=expected:raise HTTPException(401,'Choose a demo account for this app')
        return dict(s)
    def audit(db,s,action,entity):
        if s['app']=='ops':put(db,'audit',{'id':rid('AUD'),'ops_user_id':s['account_id'],'action':action,'entity_id':entity,'at':iso()})
    @app.post('/v2/auth/demo')
    def login(body:Login):
        defaults={'rider':('riders','R0001'),'driver':('drivers','D004'),'ops':('ops_users','O1')}
        if body.app not in defaults:raise HTTPException(422,'Unknown app')
        table,default=defaults[body.app];account=body.account_id or default
        with connect(path) as db:
            row=get(db,table,account)
            if not row:raise HTTPException(404,'Demo account not found')
            token='hoppr-demo-v1:'+body.app+':'+account
        return {'token':token,'account':row,'demo':True,'label':'Demo data. Not real people.'}
    @app.get('/v2/me')
    def me(authorization:str|None=Header(None)):
        s=session(authorization)
        with connect(path) as db:
            table={'rider':'riders','driver':'drivers','ops':'ops_users'}[s['app']];account=get(db,table,s['account_id']);bs=[b for b in rows(db,'bookings') if b['rider_id']==s['account_id'] or b['driver_id']==s['account_id']];wallet=[w for w in rows(db,'wallet_entries') if w['rider_id']==s['account_id']]
            return {'account':account,'app':s['app'],'wallet':sum(w['amount'] for w in wallet),'wallet_entries':wallet[-40:],'bookings':bs[-60:],'tickets':[t for t in rows(db,'tickets') if t['rider_id']==s['account_id']],'passes':[p for p in rows(db,'passes') if p['rider_id']==s['account_id']],'finance':finance(db,driver_id=s['account_id']) if s['app']=='driver' else finance(db,rider_id=s['account_id']) if s['app']=='rider' else finance(db),'modules':ROLE_MODULES.get(s['role'],[]),'demo_clock':'2026-10-09T20:00:00+05:30'}
    @app.get('/v2/airports')
    def airports():
        with connect(path) as db:return rows(db,'airports')
    @app.get('/v2/flights')
    def flights(request:Request,airport:str='DEL',date:str=Query('2026-10-09',pattern=r'^\d{4}-\d{2}-\d{2}$')):
        if airport not in health:raise HTTPException(422,'Unsupported airport')
        key=request.client.host if request.client else 'local';now=time.monotonic();limits[key]=[t for t in limits[key] if now-t<60]
        if len(limits[key])>=60:raise HTTPException(429,'Too many arrival refreshes',headers={'Retry-After':'60'})
        limits[key].append(now);ck=(airport,date)
        if len(limits)>10000:
            for expired in [k for k,v in limits.items() if not v or now-v[-1]>=60]:limits.pop(expired,None)
        if len(cache)>256:cache.pop(next(iter(cache)))
        if ck not in cache or now-cache[ck][0]>10:
            with connect(path) as db:cache[ck]=(now,[f for f in rows(db,'flights') if f['airport_id']==airport and f['date']==date])
        return {'items':cache[ck][1],'source':health[airport],'synthetic':all(f['source']=='demo' for f in cache[ck][1])}
    @app.get('/v2/health')
    def status():
        with connect(path) as db:
            for airport in health:
                r=db.execute('SELECT value FROM metadata WHERE key=?',('health:'+airport,)).fetchone()
                if r:health[airport]=json.loads(r[0])
        return {'airports':{a:dict(h,age_seconds=round((datetime.now(timezone.utc)-instant(h['last_success_at'])).total_seconds()) if h['last_success_at'] else None) for a,h in health.items()},'demo':True,'poll_seconds':30,'live_api_verified':False}
    @app.post('/v2/match')
    def match(body:Match,authorization:str|None=Header(None)):
        s=session(authorization,'rider')
        if body.ride_type not in ('pool','private') or body.max_wait not in (15,30,45):raise HTTPException(422,'Invalid ride preference')
        if body.accessibility or body.child_seat:raise HTTPException(409,'Special equipment is not verified in this demo. Contact support before booking.')
        with connect(path) as db:
            f=get(db,'flights',body.flight_id);r=get(db,'riders',s['account_id'])
            if not f:raise HTTPException(404,'Flight not found')
            if body.women_only and r['gender']!='woman':raise HTTPException(422,'Women-only requires an all-women party')
            if not any(a['id']==body.destination for a in get(db,'airports',f['airport_id'])['dropoff_areas']):raise HTTPException(422,'Choose a drop-off for this airport')
            prior=next((b for b in rows(db,'bookings') if b['rider_id']==s['account_id'] and b['flight_id']==body.flight_id and b['status'] not in ('completed','cancelled')),None)
            if prior:raise HTTPException(409,'You already have a request for this flight. Open Trips to manage it.')
            pid=rid('P');bid=rid('B');ready=instant(f['estimated'])+timedelta(minutes=22 if body.bags else 12)
            put(db,'pools',{'id':pid,'airport_id':f['airport_id'],'terminal':f['terminal'],'driver_id':None,'cab_id':None,'booking_ids':[bid],'pickup':ready.isoformat(),'end':(ready+timedelta(hours=1)).isoformat(),'date':ready.date().isoformat(),'status':'matching','seats':body.party,'bags':body.bags,'events':[]})
            b=dict(body.model_dump(),id=bid,rider_id=s['account_id'],pool_id=pid,driver_id=None,cab_id=None,status='matching',ready_time=ready.isoformat(),pickup=ready.isoformat(),gender=r['gender'],demo=True,version=0,pickup_code=f'{secrets.randbelow(9000)+1000}')
            put(db,'bookings',b);rematch(db,f['airport_id'],f['terminal']);return quote(db,get(db,'bookings',bid))
    @app.get('/v2/ride/{bid}')
    def ride(bid:str,authorization:str|None=Header(None)):
        s=session(authorization)
        with connect(path) as db:
            b=get(db,'bookings',bid)
            if not b:raise HTTPException(404,'Ride not found')
            if s['app']=='rider' and b['rider_id']!=s['account_id'] or s['app']=='driver' and b['driver_id']!=s['account_id']:raise HTTPException(403,'This ride belongs to a different demo account')
            return quote(db,b)
    @app.post('/v2/book')
    def book(body:Booking,authorization:str|None=Header(None)):
        s=session(authorization,'rider')
        if body.method not in ('upi','card','cash'):raise HTTPException(422,'Unknown payment method')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');b=get(db,'bookings',body.booking_id)
            if not b or b['rider_id']!=s['account_id']:raise HTTPException(404,'Ride not found')
            if b['status']=='booked':return quote(db,b)
            if b['status']!='matching':raise HTTPException(409,'Ride cannot be booked')
            if b['version']!=body.version:raise HTTPException(409,'Quote changed. Review before booking.')
            q=quote(db,b);transport=q['transport'];service=q['service_fee'];tax=q['tax'];gross=q['total'];promo=get(db,'promos',body.promo.upper()) if body.promo else None
            if body.promo and not promo:raise HTTPException(422,'Unknown demo promo')
            promo_amount=min(gross,promo['discount']) if promo else 0;balance=sum(w['amount'] for w in rows(db,'wallet_entries') if w['rider_id']==s['account_id']);wallet=min(balance,gross-promo_amount)
            payout=int(transport*b.get('pricing_snapshot',{}).get('driver_share',.8));p=get(db,'pools',b['pool_id'])
            payment={'id':'PAY-'+b['id'],'booking_id':b['id'],'transport':transport,'service_fee':service,'platform_fee':transport-payout+service,'tax':tax,'gross':gross,'refund':0,'net':gross,'driver_payout':payout,'driver_deduction':0,'tip':0,'method':body.method,'wallet_applied':wallet,'promo_applied':promo_amount,'remaining':gross-wallet-promo_amount,'date':p['date'],'receipt_no':'DEMO-'+b['id'],'tax_label':'Illustrative GST 5%; not a tax invoice'}
            put(db,'payments',payment)
            if wallet:put(db,'wallet_entries',{'id':'W-'+b['id'],'rider_id':s['account_id'],'booking_id':b['id'],'amount':-wallet,'reason':'Wallet applied before payment','at':iso()})
            b['status']='booked';b['price_locked']=True;put(db,'bookings',b);return quote(db,b)
    @app.post('/v2/cancel')
    def cancel(body:Mutation,authorization:str|None=Header(None)):
        s=session(authorization,'rider')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');b=get(db,'bookings',body.entity_id)
            if not b or b['rider_id']!=s['account_id']:raise HTTPException(404,'Ride not found')
            if b['status']=='cancelled':return {'status':'cancelled','idempotent':True}
            p=get(db,'pools',b['pool_id'])
            if p['status'] in ('picked_up','completed'):raise HTTPException(409,'Ride has started; contact support')
            pay=get(db,'payments','PAY-'+b['id'])
            if pay:
                paid=pay['gross']-pay.get('promo_applied',0)-(pay.get('remaining',0) if pay['method']=='cash' else 0)
                pay.update(refund=pay['gross'],net=0,driver_deduction=pay['driver_payout'],driver_payout=0,platform_fee=0,tax=0);put(db,'payments',pay)
                put(db,'wallet_entries',{'id':'REF-'+b['id'],'rider_id':s['account_id'],'booking_id':b['id'],'amount':paid,'reason':'Cancellation refund','at':iso()})
            b['status']='cancelled';put(db,'bookings',b);active_ids=[i for i in p['booking_ids'] if get(db,'bookings',i)['status']!='cancelled']
            if not active_ids:p['status']='cancelled'
            p['seats']=sum(get(db,'bookings',i)['party'] for i in active_ids);p['bags']=sum(get(db,'bookings',i)['bags'] for i in active_ids)
            p['events'].append({'at':iso(),'text':'Rider cancelled; refund ledger and driver deduction recorded'});put(db,'pools',p)
            return {'status':'cancelled','wallet_refund':paid if pay else 0}
    @app.get('/v2/notifications')
    def notifications(authorization:str|None=Header(None)):
        s=session(authorization);audience='ops' if s['app']=='ops' else s['app']+':'+s['account_id']
        with connect(path) as db:return [n for n in rows(db,'notifications') if n['audience']==audience][-30:]
    @app.post('/v2/support')
    def support(body:Mutation,authorization:str|None=Header(None)):
        s=session(authorization)
        if len(body.message.strip())<5:raise HTTPException(422,'Please describe your request')
        with connect(path) as db:
            if s['app']=='driver':notify(db,'ops',s['account_id'],'Driver support: '+body.message);return {'reference':rid('DS'),'demo':True}
            tid=rid('T');put(db,'tickets',{'id':tid,'rider_id':s['account_id'] if s['app']=='rider' else 'R0001','booking_id':body.entity_id or None,'category':body.action,'status':'open','created_at':iso(),'sla_due':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat(),'thread':[{'by':s['app'],'text':body.message,'at':iso()}]});return {'reference':tid,'demo':True}
    @app.post('/v2/account')
    def account(body:Mutation,authorization:str|None=Header(None)):
        s=session(authorization)
        with connect(path) as db:
            table='riders' if s['app']=='rider' else 'drivers';r=get(db,table,s['account_id'])
            if body.action=='online' and s['app']=='driver':
                if r['status']!='approved':raise HTTPException(409,'Ops approval required')
                r['online']=body.value=='true'
            elif body.action=='language':r['language']=body.value if body.value in ('en','hi') else 'en'
            elif body.action=='saved_place' and s['app']=='rider':r['saved_places'].append({'label':body.message or 'Saved','destination':body.value})
            elif body.action=='privacy' and s['app']=='rider':r['privacy']['analytics']=body.value=='true'
            elif body.action=='demo_verify' and s['app']=='rider':r['verified']=True
            elif body.action=='notification' and s['app']=='rider':r['notification_settings'][body.value]=body.message=='true'
            elif body.action=='shift' and s['app']=='driver':r['shift']=body.value
            elif body.action=='payout_mask' and s['app']=='driver':
                if len(body.value)!=4 or not body.value.isdigit():raise HTTPException(422,'Use four synthetic digits only')
                r['payout_mask']='Demo account •••• '+body.value
            elif body.action=='demo_document' and s['app']=='driver':
                for doc in r['documents']:
                    if doc['type']==body.value:doc['status']='pending';doc['file']='New synthetic placeholder — no personal document uploaded'
                r['status']='pending';r['online']=False
            else:raise HTTPException(422,'Unsupported preference')
            put(db,table,r);return r
    @app.post('/v2/rating')
    def rating(body:Mutation,authorization:str|None=Header(None)):
        s=session(authorization)
        if s['app'] not in ('rider','driver'):raise HTTPException(403,'Traveller or driver required')
        try:score=int(body.value)
        except ValueError:raise HTTPException(422,'Choose rating 1–5')
        if not 1<=score<=5:raise HTTPException(422,'Choose rating 1–5')
        with connect(path) as db:
            b=get(db,'bookings',body.entity_id)
            own=b and (b['rider_id']==s['account_id'] if s['app']=='rider' else b['driver_id']==s['account_id'])
            if not own or b['status']!='completed':raise HTTPException(409,'Rate after completing your own ride')
            direction='driver_to_rider' if s['app']=='driver' else 'rider_to_rider' if body.action=='coriders' else 'rider_to_driver'
            put(db,'ratings',{'id':b['id']+'-'+direction,'booking_id':b['id'],'direction':direction,'score':score,'text':body.message,'tip':0});return {'saved':True}
    @app.post('/v2/tip')
    def tip(body:Mutation,authorization:str|None=Header(None)):
        s=session(authorization,'rider')
        if body.value not in ('0','2000','5000'):raise HTTPException(422,'Choose an allowed demo tip')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');b=get(db,'bookings',body.entity_id)
            if not b or b['rider_id']!=s['account_id'] or b['status']!='completed':raise HTTPException(409,'Tip only after completing your own trip')
            p=get(db,'payments','PAY-'+b['id']);amount=int(body.value)
            if p.get('tip',0):return {'already_tipped':True}
            p['tip']=amount;p['gross']+=amount;p['net']+=amount;p['driver_payout']+=amount;put(db,'payments',p)
            return {'demo_tip':amount,'real_charge':False}
    @app.post('/v2/incident')
    def incident(body:Mutation,authorization:str|None=Header(None)):
        s=session(authorization)
        with connect(path) as db:
            p=get(db,'pools',body.entity_id)
            if not p:raise HTTPException(404,'Trip not found')
            if s['app']=='driver' and p['driver_id']!=s['account_id'] or s['app']=='rider' and not any(get(db,'bookings',i)['rider_id']==s['account_id'] for i in p['booking_ids']):raise HTTPException(403,'Not your trip')
            row={'id':rid('I'),'pool_id':p['id'],'severity':'high' if body.action=='sos' else 'low','kind':'Demo SOS' if body.action=='sos' else 'Trip issue','status':'open','notes':body.message or 'Demo event. No emergency service contacted.','created_at':iso()};put(db,'incidents',row);notify(db,'ops',row['id'],'Demo safety incident recorded');return row
    @app.get('/v2/driver/trips')
    def driver_trips(authorization:str|None=Header(None)):
        s=session(authorization,'driver')
        with connect(path) as db:return [full_pool(db,p) for p in rows(db,'pools') if p['driver_id']==s['account_id'] and p['status'] in ACTIVE]
    @app.post('/v2/driver/step')
    def driver_step(body:Step,authorization:str|None=Header(None)):
        s=session(authorization,'driver')
        with connect(path) as db:
            p=get(db,'pools',body.pool_id)
            if not p or p['driver_id']!=s['account_id']:raise HTTPException(404,'Assigned trip not found')
            expected={'offered':'accepted','accepted':'en_route','en_route':'arrived','arrived':'picked_up','picked_up':'completed'}
            if body.step=='decline' and p['status']=='offered':
                if not body.reason:raise HTTPException(422,'Select a decline reason')
                p['status']='matching';p['driver_id']=None;p['cab_id']=None;notify(db,'ops',p['id'],'Driver declined: '+body.reason)
            else:
                if expected.get(p['status'])!=body.step:raise HTTPException(409,'Invalid trip stage')
                if body.step=='picked_up':
                    for bid in p['booking_ids']:
                        b=get(db,'bookings',bid)
                        if b['status']=='cancelled':continue
                        if b['status']!='booked':raise HTTPException(409,'Only confirmed passengers may board')
                        if body.codes.get(bid)!=b['pickup_code']:raise HTTPException(422,'Check each passenger pickup code')
                p['status']=body.step
            p['events'].append({'at':iso(),'text':body.step.replace('_',' ')});put(db,'pools',p)
            for bid in p['booking_ids']:
                b=get(db,'bookings',bid)
                if body.step=='completed' and b['status']!='cancelled':b['status']='completed';put(db,'bookings',b)
                notify(db,'rider:'+b['rider_id'],bid,'Your trip is '+p['status'].replace('_',' '))
            return full_pool(db,p)
    @app.get('/v2/ops/summary')
    def summary(authorization:str|None=Header(None)):
        s=session(authorization,'ops')
        with connect(path) as db:
            pools=[p for p in rows(db,'pools') if p['status']!='superseded'];bookings=rows(db,'bookings');sizes=Counter(len(p['booking_ids']) for p in pools);finance_data=finance(db);drivers=rows(db,'drivers')
            wallets=rows(db,'wallet_entries');finance_data['wallet_liability']=sum(w['amount'] for w in wallets)
            return {'pool_count':len(pools),'booking_count':len(bookings),'solo_percent':round(sizes[1]/max(1,len(pools))*100,1),'fill_rate':round(sum(p['seats'] for p in pools)/max(1,len(pools)*4)*100,1),'average_riders':round(sum(p['seats'] for p in pools)/max(1,len(pools)),2),'fewer_cars_percent':round((1-len(pools)/max(1,len(bookings)))*100,1),'cancellations':sum(b['status']=='cancelled' for b in bookings),'active_pools':sum(p['status'] in ACTIVE for p in pools),'online_drivers':sum(d['online'] for d in drivers),'rider_savings':sum(max(0,b['solo_fare']-b['locked_transport']) for b in bookings if b['status']!='cancelled'),'finance':finance_data if s['role'] in ('admin','finance') else None,'history':finance_data['by_day'][:14],'synthetic':True,'not_measured':['match_time','on_time_pickup','gps_locations']}
    @app.get('/v2/ops/table/{table}')
    def table_view(table:str,q:str='',sort:str='id',descending:bool=False,page:int=Query(1,ge=1),size:int=Query(50,ge=1,le=200),authorization:str|None=Header(None)):
        s=session(authorization,'ops')
        if table not in ROLE_MODULES[s['role']]:raise HTTPException(403,'Module unavailable for this demo role')
        with connect(path) as db:
            items=rows(db,table);items=[r for r in items if q.casefold() in json.dumps(r).casefold()]
            items.sort(key=lambda r:(0,r.get(sort)) if isinstance(r.get(sort),(int,float)) else (1,str(r.get(sort,''))),reverse=descending)
            return {'items':items[(page-1)*size:page*size],'total':len(items),'page':page,'pages':(len(items)+size-1)//size}
    @app.get('/v2/ops/export/{table}')
    def export(table:str,authorization:str|None=Header(None)):
        s=session(authorization,'ops')
        if table not in ROLE_MODULES[s['role']]:raise HTTPException(403,'Unavailable module')
        with connect(path) as db:
            items=rows(db,table);fields=list(dict.fromkeys(k for r in items for k in r));out=io.StringIO();writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
            for r in items:
                safe={k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()}
                safe={k:"'"+str(v) if str(v).startswith(('=','+','-','@')) else v for k,v in safe.items()};writer.writerow(safe)
            audit(db,s,'export_csv',table)
        return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename=hoppr-demo-{table}.csv'})
    @app.post('/v2/ops/action')
    def ops_action(body:Mutation,authorization:str|None=Header(None)):
        s=session(authorization,'ops');role=s['role']
        with connect(path) as db:
            if body.action=='eta':
                if role not in ('admin','ops_lead'):raise HTTPException(403,'Operations role required')
                affected=update_eta(db,body.entity_id,body.value);cache.clear();result={'affected':affected}
            elif body.action=='rematch':
                if role not in ('admin','ops_lead'):raise HTTPException(403,'Operations role required')
                p=get(db,'pools',body.entity_id)
                if not p or p['status'] not in ('matching','offered'):raise HTTPException(409,'Only queued pools can be re-matched')
                result={'pools':rematch(db,p['airport_id'],p['terminal'],set(p['booking_ids']))}
            elif body.action in ('approve','suspend','reinstate'):
                if role not in ('admin','ops_lead'):raise HTTPException(403,'Operations role required')
                d=get(db,'drivers',body.entity_id)
                if not d:raise HTTPException(404,'Driver not found')
                d['status']='suspended' if body.action=='suspend' else 'approved';d['online']=False;put(db,'drivers',d);result=d
                if body.action=='approve':
                    for doc in d['documents']:doc['status']='approved'
                    put(db,'drivers',d)
            elif body.action in ('resolve','reply'):
                if role not in ('admin','ops_lead','support'):raise HTTPException(403,'Support role required')
                table='incidents' if body.entity_id.startswith('I') else 'tickets';r=get(db,table,body.entity_id)
                if not r:raise HTTPException(404,'Case not found')
                if body.action=='resolve':
                    r['status']='resolved';r['resolution']=body.message or 'Resolved in demo Ops';r['resolved_at']=iso()
                else:r.setdefault('thread',[]).append({'by':'support','text':body.message,'at':iso()})
                put(db,table,r);result=r
            elif body.action=='pricing':
                if role not in ('admin','finance'):raise HTTPException(403,'Finance role required')
                try:
                    settings=json.loads(body.value);airport=settings.pop('airport',body.entity_id)
                    if airport not in health:raise ValueError('airport')
                    for field,bounds in {'base':(0,1000),'per_km':(0,100),'night_multiplier':(1,3),'detour':(1,2),'service_fee':(0,100),'driver_share':(0,1)}.items():
                        value=float(settings[field])
                        if not bounds[0]<=value<=bounds[1]:raise ValueError(field)
                        settings[field]=value
                except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid pricing rules')
                db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('pricing:'+airport,json.dumps(settings)));result={'saved_rules':settings,'applies_to_new_quotes':True,'locked_prices_preserved':True}
            else:raise HTTPException(422,'Unknown operation')
            audit(db,s,body.action,body.entity_id);return result
    dist=ROOT/'web'/'dist'
    if dist.exists():
        app.mount('/assets',StaticFiles(directory=dist/'assets'),name='v2_assets')
        @app.get('/sw.js')
        def worker():return FileResponse(dist/'sw.js',media_type='application/javascript')
        @app.get('/manifest-{which}.webmanifest')
        def manifest(which:str):
            if which not in ('rider','driver'):raise HTTPException(404)
            return FileResponse(dist/f'manifest-{which}.webmanifest')
        @app.get('/icon.svg')
        def icon():return FileResponse(dist/'icon.svg')
        @app.get('/icon-{size}.png')
        def raster_icon(size:str):
            if size not in ('192','512'):raise HTTPException(404)
            return FileResponse(dist/f'icon-{size}.png')
        @app.get('/')
        @app.get('/rider')
        @app.get('/driver')
        @app.get('/ops')
        def frontend():return FileResponse(dist/'index.html')
    return app

app=create_app()
