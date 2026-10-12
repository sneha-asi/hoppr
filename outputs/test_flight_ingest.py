import copy
import sqlite3

import pytest
from flight_ingest import (AeroDataBoxProvider,AirportScraper,DemoProvider,ProviderError,
    fetch_first_success,init_db,normalise_flight,poll_once,upsert_flights)

# Hand-written fixture, not captured from a live call. TODO(verify): confirm
# these fields and their meanings against actual AeroDataBox responses.
SAMPLE = {
    'number':'6E 123','airline':{'iata':'6E','name':'IndiGo'},'status':'Delayed',
    'departure':{'airport':{'iata':'BOM','name':'Mumbai'}},
    'arrival':{'terminal':'3',
        'scheduledTime':{'utc':'2026-10-09T16:30:00Z','local':'2026-10-09T22:00:00+05:30'},
        'revisedTime':{'utc':'2026-10-09T16:55:00Z','local':'2026-10-09T22:25:00+05:30'}}
}


def test_normaliser_handwritten_sample():
    before = copy.deepcopy(SAMPLE)
    assert normalise_flight(SAMPLE,'DEL') == {
        'id':'DEL:6E123:2026-10-09','airport':'DEL','flight_no':'6E123','airline':'6E',
        'origin':'BOM','terminal':'3','scheduled':'2026-10-09T16:30:00+00:00',
        'estimated':'2026-10-09T16:55:00+00:00','delay_min':25.0,
        'status':'delayed','source':'aerodatabox'}
    assert SAMPLE == before


def test_missing_eta_and_optional_fields():
    row = copy.deepcopy(SAMPLE)
    del row['arrival']['revisedTime']
    del row['arrival']['terminal']
    del row['airline']; del row['departure']; del row['status']
    flight = normalise_flight(row,'DEL')
    assert flight['estimated'] == flight['scheduled']
    assert flight['delay_min'] == 0
    assert flight['origin'] is None and flight['airline'] is None and flight['terminal'] is None
    assert flight['status'] == 'unknown'


def test_reject_ambiguous_timestamp():
    row = copy.deepcopy(SAMPLE)
    row['arrival']['scheduledTime'] = {'local':'2026-10-09T22:00:00'}
    with pytest.raises(ValueError):
        normalise_flight(row,'DEL')


@pytest.mark.parametrize('row',[[], {'arrival':[]},dict(SAMPLE,airline='invalid')])
def test_reject_malformed_shape(row):
    with pytest.raises(ValueError):
        normalise_flight(row,'DEL')


def test_upsert_eta_change_only_and_stable_id():
    db = sqlite3.connect(':memory:'); init_db(db)
    first = normalise_flight(SAMPLE,'DEL')
    assert upsert_flights(db,[first]) == []
    assert upsert_flights(db,[first]) == []
    row = copy.deepcopy(SAMPLE)
    row['arrival']['revisedTime']['utc'] = '2026-10-09T17:10:00Z'
    second = normalise_flight(row,'DEL')
    assert second['id'] == first['id']
    assert upsert_flights(db,[second]) == [first['id']]
    assert db.execute('SELECT COUNT(*) FROM flights').fetchone()[0] == 1
    assert db.execute('SELECT old_estimated,new_estimated FROM changes').fetchone() == (first['estimated'],second['estimated'])
    second['status'] = 'landed'
    assert upsert_flights(db,[second]) == []
    second['estimated'] = '2026-10-09T22:40:00+05:30'
    assert upsert_flights(db,[second]) == []  # Same instant, different offset.


def test_upsert_rollback():
    db = sqlite3.connect(':memory:'); init_db(db)
    good = normalise_flight(SAMPLE,'DEL')
    bad = dict(good,id='bad',estimated='invalid')
    with pytest.raises(ValueError):
        upsert_flights(db,[good,bad])
    assert db.execute('SELECT COUNT(*) FROM flights').fetchone()[0] == 0


def test_provider_chain_first_success_and_empty_success():
    calls = []
    class Fake:
        name = 'fake'
        def __init__(self,result=None,fail=False):
            self.result=result; self.fail=fail
        def fetch(self,airport):
            calls.append(airport)
            if self.fail:
                raise ProviderError('failed')
            return self.result
    assert fetch_first_success('DEL',[Fake(fail=True),Fake([]),Fake(['wrong'])]) == []
    assert calls == ['DEL','DEL']


def test_scraper_skeleton_and_missing_key():
    with pytest.raises(NotImplementedError):
        AirportScraper().fetch('DEL')
    with pytest.raises(ProviderError):
        AeroDataBoxProvider(key='').fetch('DEL')


def test_offline_poll_loads_48_without_network(monkeypatch):
    from pathlib import Path
    import flight_ingest
    def forbidden(*args,**kwargs):
        raise AssertionError('Network used in offline test')
    monkeypatch.setattr(flight_ingest,'urlopen',forbidden)
    db = sqlite3.connect(':memory:'); init_db(db)
    providers = [DemoProvider(Path(__file__).with_name('airpool_demo_data.json'))]
    assert poll_once(db,providers) == []
    assert poll_once(db,providers) == []
    assert db.execute('SELECT COUNT(*) FROM flights').fetchone()[0] == 48
    assert db.execute('SELECT DISTINCT source FROM flights').fetchall() == [('demo',)]
    assert db.execute('SELECT COUNT(*) FROM changes').fetchone()[0] == 0


def test_each_failure_is_structured_and_secrets_are_not_logged(caplog):
    import json
    class Broken:
        def __init__(self,name,error):
            self.name=name;self.error=error
        def fetch(self,airport):
            raise self.error
    providers=[Broken('aerodatabox',ProviderError('SECRET_KEY',code='http_error',http_status=429)),
               Broken('scraper',NotImplementedError('SECRET_BODY')),
               Broken('custom',RuntimeError('SECRET_TOKEN'))]
    with pytest.raises(ProviderError):
        fetch_first_success('DEL',providers)
    records=[r for r in caplog.records if getattr(r,'event',None)=='provider_failure']
    assert len(records)==3
    payloads=[json.loads(r.getMessage()) for r in records]
    assert [p['attempt'] for p in payloads]==[1,2,3]
    assert payloads[0]['http_status']==429
    assert payloads[2]['error_code']=='unexpected_error'
    assert all(p['airport']=='DEL' and p['timestamp'] for p in payloads)
    assert 'SECRET' not in caplog.text


def test_health_keeps_last_success_when_all_providers_fail():
    db=sqlite3.connect(':memory:');init_db(db)
    class Empty:
        name='verified-fake'
        def fetch(self,airport):
            return []
    assert poll_once(db,[Empty()],airports=('DEL',))==[]
    original=db.execute('SELECT last_success_at,source,flight_count FROM ingest_health').fetchone()
    assert original[0] and original[1:] == ('verified-fake',0)
    poll_once(db,[AirportScraper()],airports=('DEL',))
    assert db.execute('SELECT last_success_at,source,flight_count FROM ingest_health').fetchone()==original
    assert db.execute('SELECT last_attempt_ok,last_error FROM ingest_health').fetchone()==(0,'all_providers_failed')


def test_ingest_health_and_flights_commit_atomically():
    db=sqlite3.connect(':memory:');init_db(db)
    good=normalise_flight(SAMPLE,'DEL')
    bad=dict(good,id='bad',estimated='invalid')
    with pytest.raises(ValueError):
        upsert_flights(db,[good,bad],ingest=('DEL','fake',2))
    assert db.execute('SELECT COUNT(*) FROM ingest_health').fetchone()[0]==0
