import asyncio
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api import create_app
from flight_ingest import upsert_flights


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path/'test.sqlite3',background=False)
    with TestClient(app) as client:
        yield client


def flight(client):
    return client.get('/flights?airport=DEL').json()[0]


def request(client,**overrides):
    body = dict(flight_id=flight(client)['id'],destination='DEL-A01',bags=0,
                party=1,max_wait=30,women_only=False)
    body.update(overrides)
    response = client.post('/match',json=body)
    assert response.status_code==200,response.text
    return response.json()


def refresh(client,match):
    return client.get('/match/'+match['match_id']).json()


def book(client,match):
    current = refresh(client,match)
    response = client.post('/book',json=dict(match_id=current['match_id'],quote_version=current['quote_version']))
    assert response.status_code==200,response.text
    return response.json()


def test_flights_destinations_and_invalid_airport(client):
    for airport in ('DEL','BOM','BLR'):
        rows = client.get('/flights',params={'airport':airport}).json()
        assert len(rows)==16 and all(r['airport']==airport for r in rows)
        assert len(client.get('/destinations',params={'airport':airport}).json())==12
    assert client.get('/flights?airport=XXX').status_code==422


def test_solo_option_cap_and_party_seats(client):
    result = request(client,party=3)
    assert result['option']=='solo'
    assert result['total_fare']<=result['solo_fare']
    assert result['total_fare']<=result['solo_price_cap']
    assert result['per_seat_fare']%10==0
    assert result['total_fare']==result['per_seat_fare']*3
    second = request(client)
    assert len(second['group'])==2
    third = request(client)
    assert third['option']=='solo'


def test_pool_price_savings_and_stale_quote(client):
    first = request(client)
    second = request(client)
    assert second['option']=='pool' and len(second['group'])==2
    assert second['savings']>0
    assert second['savings']==pytest.approx(second['solo_fare']-second['total_fare'])
    response = client.post('/book',json=dict(match_id=first['match_id'],quote_version=first['quote_version']))
    assert response.status_code==409
    locked = book(client,first)
    assert re.fullmatch(r'\d{4}',locked['pickup_code'])
    assert locked['price_locked']
    request(client)
    assert refresh(client,first)['total_fare']==locked['total_fare']
    retry = client.post('/book',json=dict(match_id=first['match_id'],quote_version=1)).json()
    assert retry['pickup_code']==locked['pickup_code'] and retry['total_fare']==locked['total_fare']


def test_women_only_unknown_gender_and_luggage(client):
    first = request(client,women_only=True)
    second = request(client)
    assert second['option']=='solo'  # Unknown gender can't enter women-only pool.
    third = request(client,gender='woman',bags=4)
    assert len(third['group'])==2
    fourth = request(client,gender='woman',bags=1)
    assert first['match_id'] not in [r['id'] for r in fourth['group']]


@pytest.mark.parametrize('overrides',[dict(party=5),dict(bags=5),dict(max_wait=-1),
    dict(women_only=True,gender='man'),dict(destination='BOM-A01')])
def test_input_validation(client,overrides):
    body=dict(flight_id=flight(client)['id'],destination='DEL-A01',bags=0,party=1,max_wait=30,women_only=False)
    body.update(overrides)
    assert client.post('/match',json=body).status_code==422


def test_unknown_flight_and_booking(client):
    body=dict(flight_id='missing',destination='DEL-A01',bags=0,party=1,max_wait=30,women_only=False)
    assert client.post('/match',json=body).status_code==404
    assert client.post('/book',json=dict(match_id='missing',quote_version=1)).status_code==404


def test_driver_workflow_pickup_verification_and_ops(client):
    first = request(client)
    second = request(client)
    first = book(client,first); second = book(client,second)
    trip_id = first['trip_id']
    trips = client.get('/driver/trip',params={'trip_id':trip_id}).json()
    assert len(trips)==1 and trips[0]['occupied_seats']==2
    assert all('pickup_code' not in r for r in trips[0]['riders'])
    summary = client.get('/ops/summary').json()
    assert summary['cabs_needed']==1 and summary['fewer_cars_percent']==50
    assert summary['average_riders_per_cab']==2 and summary['rider_savings']>0
    assert len(summary['history_14_days'])==14
    assert client.post('/driver/step',json=dict(trip_id=trip_id,step='completed')).status_code==409
    for step in ('en_route','arrived'):
        assert client.post('/driver/step',json=dict(trip_id=trip_id,step=step)).status_code==200
    assert client.post('/driver/step',json=dict(trip_id=trip_id,step='picked_up')).status_code==422
    codes = {first['match_id']:first['pickup_code'],second['match_id']:second['pickup_code']}
    assert client.post('/driver/step',json=dict(trip_id=trip_id,step='picked_up',pickup_codes=codes)).status_code==200
    assert client.post('/driver/step',json=dict(trip_id=trip_id,step='completed')).status_code==200
    assert client.get('/driver/trip').json()==[]
    assert client.get('/ops/summary').json()['active_cabs_needed']==0


def change_eta(client,identity,minutes):
    store = client.app.state.store
    with store.transaction() as db:
        row = dict(db.execute('SELECT * FROM flights WHERE id=?',(identity,)).fetchone())
    row['estimated']=(datetime.fromisoformat(row['estimated'])+timedelta(minutes=minutes)).isoformat()
    row['delay_min']+=minutes
    with store.connect() as db:
        assert upsert_flights(db,[row])==[identity]
    return row


def test_changed_flight_rematches_and_preserves_locked_price(client):
    f = flight(client)
    # Create a second flight at the same pickup and ETA to isolate the delay.
    f2=dict(f,id='test-flight-2',flight_no='6E999')
    store = client.app.state.store
    with store.connect() as db:
        upsert_flights(db,[f2])
    first=request(client,flight_id=f['id'],max_wait=15)
    second=request(client,flight_id=f2['id'],max_wait=15)
    assert len(second['group'])==2
    first=book(client,first); second=book(client,second)
    unrelated=request(client,destination='DEL-A12')
    unrelated_trip=unrelated['trip_id']
    change_eta(client,f2['id'],70)
    assert store.process_changes()==[f2['id']]
    for original in (first,second):
        updated=refresh(client,original)
        assert updated['option']=='solo' and len(updated['group'])==1
        assert updated['total_fare']==original['total_fare']
        notes=client.get('/notifications',params={'booking_id':original['match_id']}).json()
        assert len(notes)==1 and notes[0]['flight_id']==f2['id']
    assert refresh(client,unrelated)['trip_id']==unrelated_trip
    assert store.process_changes()==[]
    assert len(client.get('/notifications',params={'booking_id':first['match_id']}).json())==1


def test_dispatch_drops_unconfirmed_and_new_rider_cannot_join(client):
    first=request(client); second=request(client)
    first=book(client,first)
    response=client.post('/driver/step',json=dict(trip_id=first['trip_id'],step='en_route'))
    assert response.status_code==200
    assert len(response.json()['riders'])==1
    assert refresh(client,second)['trip_id']!=first['trip_id']
    third=request(client)
    assert first['match_id'] not in [r['id'] for r in third['group']]


def test_background_tick_handles_changes_without_network(tmp_path):
    state={'delay':0,'calls':0}
    from flight_ingest import DemoProvider
    from pathlib import Path
    class Provider:
        name='fake'
        def fetch(self,airport):
            state['calls']+=1
            rows=DemoProvider(Path(__file__).with_name('airpool_demo_data.json')).fetch(airport)
            for r in rows:
                r['estimated']=(datetime.fromisoformat(r['estimated'])+timedelta(minutes=state['delay'])).isoformat()
            return rows
    app=create_app(db_path=tmp_path/'bg.sqlite3',providers=[Provider()],poll_seconds=0.03)
    with TestClient(app) as client:
        first=book(client,request(client))
        state['delay']=70
        # Drive the event loop until the observable condition, without arbitrary sleeps.
        async def wait_for_notification():
            for _ in range(200):
                with app.state.store.transaction() as db:
                    count=db.execute('SELECT COUNT(*) FROM notifications WHERE booking_id=?',(first['match_id'],)).fetchone()[0]
                if count:
                    return True
                await asyncio.sleep(0.01)
            return False
        assert client.portal.call(wait_for_notification)
        assert refresh(client,first)['total_fare']==first['total_fare']
        assert state['calls']>=6


def test_bookings_persist_after_restart(tmp_path):
    path=tmp_path/'persistent.sqlite3'
    with TestClient(create_app(db_path=path,background=False)) as client:
        locked=book(client,request(client))
    with TestClient(create_app(db_path=path,background=False)) as client:
        assert refresh(client,locked)['pickup_code']==locked['pickup_code']
        assert refresh(client,locked)['total_fare']==locked['total_fare']


def test_solo_cap_applies_when_no_pool_exists(tmp_path):
    with TestClient(create_app(db_path=tmp_path/'cap.sqlite3',background=False,solo_cap=500)) as client:
        result=request(client)
        assert result['option']=='solo'
        assert result['solo_fare']>500
        assert result['total_fare']==500
        assert book(client,result)['total_fare']==500


def test_pending_eta_change_is_processed_on_restart(tmp_path):
    path=tmp_path/'restart.sqlite3'
    with TestClient(create_app(db_path=path,background=False)) as client:
        locked=book(client,request(client))
        change_eta(client,flight(client)['id'],70)
    with TestClient(create_app(db_path=path,background=False)) as client:
        notes=client.get('/notifications',params={'booking_id':locked['match_id']}).json()
        assert len(notes)==1
        assert refresh(client,locked)['total_fare']==locked['total_fare']


def test_active_trip_eta_notifies_without_moving_trip(client):
    locked=book(client,request(client))
    assert client.post('/driver/step',json=dict(trip_id=locked['trip_id'],step='en_route')).status_code==200
    change_eta(client,flight(client)['id'],70)
    client.app.state.store.process_changes()
    assert refresh(client,locked)['trip_id']==locked['trip_id']
    assert len(client.get('/notifications',params={'booking_id':locked['match_id']}).json())==1


def test_no_driver_still_returns_locked_booking(client):
    client.app.state.store.demo['drivers']=[]
    locked=book(client,request(client))
    assert locked['driver_status']=='awaiting_driver'
    assert locked['price_locked']
    assert client.get('/ops/summary').json()['awaiting_driver']==1
    assert client.post('/driver/step',json=dict(trip_id=locked['trip_id'],step='en_route')).status_code==409


def test_wallet_applied_first_and_refund_idempotent(client):
    quote=request(client)
    body=dict(match_id=quote['match_id'],quote_version=quote['quote_version'],wallet_id='wallet-A',payment_method='upi')
    locked=client.post('/book',json=body).json()
    assert locked['payment']['wallet_applied']==150
    assert locked['payment']['payment_amount']==locked['total_fare']-150
    assert client.get('/wallet?wallet_id=wallet-A').json()['balance']==0
    assert client.post('/book',json=body).json()['pickup_code']==locked['pickup_code']
    cancel=dict(booking_id=quote['match_id'],wallet_id='wallet-A',reason='pool_fell_through')
    assert client.post('/cancel',json=dict(cancel,wallet_id='wrong')).status_code==403
    refunded=client.post('/cancel',json=cancel).json()
    assert refunded['wallet_refund']==locked['total_fare']
    balance=client.get('/wallet?wallet_id=wallet-A').json()['balance']
    assert balance==locked['total_fare']
    assert client.post('/cancel',json=cancel).json()['already_refunded']
    assert client.get('/wallet?wallet_id=wallet-A').json()['balance']==balance
    assert client.get('/ops/summary').json()['cabs_needed']==0
    assert refresh(client,quote)['status']=='cancelled'
    assert request(client)['option']=='solo'


def test_cash_refunds_only_wallet_credit(client):
    quote=request(client)
    body=dict(match_id=quote['match_id'],quote_version=quote['quote_version'],wallet_id='cash-wallet',payment_method='cash')
    client.post('/book',json=body)
    response=client.post('/cancel',json=dict(booking_id=quote['match_id'],wallet_id='cash-wallet')).json()
    assert response['wallet_refund']==150


def test_support_and_static_frontend(client):
    assert client.get('/').status_code==200
    assert 'Land together.' in client.get('/').text
    assert client.get('/static/app.js').status_code==200
    assert client.post('/support',json=dict(wallet_id='demo',message='My driver has not arrived')).json()['status']=='saved'


class FakeClock:
    def __init__(self):
        self.value=100.0
    def __call__(self):
        return self.value


def test_flights_rate_limit_shared_across_airports_and_resets(tmp_path):
    clock=FakeClock()
    app=create_app(db_path=tmp_path/'rate.sqlite3',background=False,
                   flights_rate_limit=2,flights_rate_window=60,clock=clock)
    with TestClient(app) as client:
        assert client.get('/flights?airport=DEL').headers['RateLimit-Remaining']=='1'
        assert client.get('/flights?airport=BOM').status_code==200
        limited=client.get('/flights?airport=BLR',headers={'X-Forwarded-For':'spoofed'})
        assert limited.status_code==429
        assert limited.headers['Retry-After']=='60'
        assert limited.headers['RateLimit-Remaining']=='0'
        assert client.get('/health').status_code==200  # Other endpoints aren't limited.
        clock.value+=60
        assert client.get('/flights?airport=DEL').status_code==200


def test_flights_cache_ttl_and_airport_isolation(tmp_path):
    clock=FakeClock()
    app=create_app(db_path=tmp_path/'cache.sqlite3',background=False,flights_cache_ttl=10,clock=clock)
    with TestClient(app) as client:
        first=client.get('/flights?airport=DEL')
        assert first.headers['X-Cache']=='MISS'
        assert client.get('/flights?airport=DEL').headers['X-Cache']=='HIT'
        assert client.get('/flights?airport=BOM').headers['X-Cache']=='MISS'
        identity=first.json()[0]['id']
        with app.state.store.transaction() as db:
            db.execute("UPDATE flights SET status='landed' WHERE id=?",(identity,))
        assert client.get('/flights?airport=DEL').json()[0]['status']!='landed'
        clock.value+=10
        expired=client.get('/flights?airport=DEL')
        assert expired.headers['X-Cache']=='MISS' and expired.json()[0]['status']=='landed'


def test_ingest_invalidates_cache_and_health_persists(tmp_path):
    path=tmp_path/'health.sqlite3'
    app=create_app(db_path=path,background=False)
    with TestClient(app) as client:
        assert all(a['status']=='never_ingested' for a in client.get('/health').json()['airports'])
        client.get('/flights?airport=DEL')
        app.state.store.ingest_tick()
        assert client.get('/flights?airport=DEL').headers['X-Cache']=='MISS'
        health=client.get('/health').json()
        assert health['status']=='ok'
        assert all(a['source']=='demo' and a['synthetic'] and a['last_success_at'] for a in health['airports'])
        successes={a['airport']:a['last_success_at'] for a in health['airports']}
    with TestClient(create_app(db_path=path,background=False)) as client:
        assert {a['airport']:a['last_success_at'] for a in client.get('/health').json()['airports']}==successes


def test_health_failure_and_staleness(client):
    store=client.app.state.store
    store.ingest_tick()
    from flight_ingest import AirportScraper
    store.providers=[AirportScraper()]
    store.ingest_tick()
    health=client.get('/health').json()
    assert health['status']=='degraded'
    assert all(a['status']=='degraded' and a['source']=='demo' for a in health['airports'])
    with store.transaction() as db:
        db.execute("UPDATE ingest_health SET last_success_at='2020-01-01T00:00:00+00:00'")
    assert all(a['status']=='stale' for a in client.get('/health').json()['airports'])


def test_zero_cache_ttl_disables_cache(tmp_path):
    with TestClient(create_app(db_path=tmp_path/'nocache.sqlite3',background=False,flights_cache_ttl=0)) as client:
        assert client.get('/flights').headers['X-Cache']=='MISS'
        assert client.get('/flights').headers['X-Cache']=='MISS'


def test_private_rides_never_join_pools_even_after_eta_change(client):
    private=request(client,ride_type='private')
    first=request(client)
    second=request(client)
    assert len(second['group'])==2
    assert len(refresh(client,private)['group'])==1
    assert refresh(client,private)['ride_type']=='private'
    change_eta(client,flight(client)['id'],25)
    client.app.state.store.process_changes()
    assert len(refresh(client,private)['group'])==1
    assert private['match_id'] not in [r['id'] for r in refresh(client,first)['group']]
