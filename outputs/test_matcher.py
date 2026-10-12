"""Run with: python -m pytest outputs/test_matcher.py -q"""
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from matcher import (Rider, compatible, distance_km, fits_cab, match_riders,
                     quote_fare, rematch_flight, rider_from_demo, round_rs10)

NOW = datetime.fromisoformat('2026-10-09T22:12+05:30')


def rider(i, **changes):
    values = dict(id=str(i),ready_time=NOW,max_wait_min=15,lat=28.4949,lng=77.0895,
                  gender='woman',solo_fare=Decimal('1200'),flight_id='F1')
    values.update(changes)
    return Rider(**values)


DATA = json.loads(Path(__file__).with_name('airpool_demo_data.json').read_text(encoding='utf-8'))
AREAS = {a['id']:a for h in DATA['airports'] for a in h['dropoff_areas']}


@pytest.mark.parametrize('case',DATA['scenario_tests'],ids=lambda c:c['name'])
def test_seven_existing_scenarios(case):
    members = [rider_from_demo(p,AREAS) for p in case['passengers']]
    assert [len(g) for g in match_riders(members)] == case['expected_pool_sizes']


def test_party_of_three_uses_three_seats():
    party,one,two = rider('a',party_size=3),rider('b'),rider('c')
    assert fits_cab((party,one))
    assert not fits_cab((party,one,two))
    assert match_riders((two,party,one)) == ((party,one),(two,))


def test_delay_moves_rider_out_and_leaves_other_groups_untouched():
    a,b = rider('a'),rider('b',flight_id='F2')
    unrelated = (rider('c',lat=19,lng=72,flight_id='F3'),)
    groups = ((a,b),unrelated)
    result = rematch_flight(groups,'F2',NOW+timedelta(minutes=28))
    assert result.groups[0] == (a,)
    assert result.groups[1] is unrelated
    assert result.groups[2][0].id == 'b'
    assert result.groups[2][0].ready_time == NOW+timedelta(minutes=40)
    assert result.affected_rider_ids == ('a','b')
    assert result.changed_flight_rider_ids == ('b',)
    assert groups == ((a,b),unrelated)
    assert b.ready_time == NOW


def test_rematch_baggage_and_multiple_affected_groups():
    a,b = rider('a',large_bags=1),rider('b',flight_id='F2')
    c = rider('c',ready_time=NOW+timedelta(minutes=40))
    result = rematch_flight(((a,b),(c,)),'F1',NOW+timedelta(minutes=18))
    changed = {r.id:r for g in result.groups for r in g}
    assert changed['a'].ready_time == NOW+timedelta(minutes=40)
    assert changed['c'].ready_time == NOW+timedelta(minutes=30)
    assert [tuple(r.id for r in g) for g in result.groups] == [('b',),('c','a')]


def test_unknown_flight_is_noop():
    group = (rider('a'),)
    result = rematch_flight((group,),'missing',NOW)
    assert result.groups[0] is group
    assert result.affected_rider_ids == ()


def test_stricter_wait_limit_is_symmetric_and_inclusive():
    a = rider('a',max_wait_min=15)
    b = rider('b',max_wait_min=45,ready_time=NOW+timedelta(minutes=15))
    assert compatible(a,b) and compatible(b,a)
    b = replace(b,ready_time=b.ready_time+timedelta(seconds=1))
    assert not compatible(a,b) and not compatible(b,a)


def test_distance_boundary_and_nearby_different_corridor():
    from math import degrees
    a = rider('a',lat=0,lng=0)
    b = rider('b',lat=degrees(12/6371.0088),lng=0)
    assert distance_km(a,b) == pytest.approx(12)
    assert compatible(a,b)
    assert not compatible(a,replace(b,lat=b.lat+0.00001))


def test_every_member_must_match_no_transitive_chain():
    a,b,c = rider('a',lat=0,lng=0),rider('b',lat=0,lng=0.08),rider('c',lat=0,lng=0.16)
    assert compatible(a,b) and compatible(b,c) and not compatible(a,c)
    assert match_riders((c,b,a)) == ((a,b),(c,))


def test_women_only_symmetric_and_nonbinary_excluded():
    a = rider('a',women_only=True)
    for gender in ('man','nonbinary'):
        b = rider('b',gender=gender)
        assert not compatible(a,b) and not compatible(b,a)
    assert compatible(a,rider('b'))
    assert compatible(rider('a'),rider('b',gender='man'))


def test_capacity_exact_boundary_and_luggage_overflow():
    assert fits_cab((rider('a',party_size=3,large_bags=3),rider('b',large_bags=1)))
    assert not fits_cab((rider('a',large_bags=3),rider('b',large_bags=2)))


def test_fare_uses_max_and_seat_weighting():
    quote = quote_fare((rider('a',party_size=3,solo_fare=1000),rider('b',solo_fare=1200)))
    assert quote.pool_fare == Decimal('1380')
    assert quote.fare_per_seat == Decimal('350')
    assert quote.allocations == (('a',Decimal('1050')),('b',Decimal('350')))
    assert quote.collected_total == Decimal('1400')
    assert quote.rounding_delta == Decimal('20')


def test_solo_party_no_detour_and_rounding_half_up():
    quote = quote_fare((rider('a',party_size=3,solo_fare=1200),))
    assert quote.pool_fare == 1200 and quote.allocations == (('a',Decimal('1200')),)
    assert round_rs10(Decimal('405')) == 410
    assert round_rs10(Decimal('404.99')) == 400


def test_empty_and_duplicate_inputs():
    assert match_riders(()) == ()
    with pytest.raises(ValueError):
        match_riders((rider('a'),rider('a')))
    with pytest.raises(ValueError):
        quote_fare(())


@pytest.mark.parametrize('changes',[dict(party_size=5),dict(large_bags=-1),
    dict(max_wait_min=-1),dict(lat=91),dict(solo_fare=-1),dict(gender='man',women_only=True)])
def test_invalid_rider(changes):
    with pytest.raises(ValueError):
        rider('a',**changes)
