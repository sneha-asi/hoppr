"""Generate synthetic airport ride-sharing data using only the Python stdlib.

Run: python gen_demo_data.py [--seed 20261009] [--output PATH]
Road distances and journey times are hand-set planning estimates, not live routes.
Flights, people, plates and trips are fictional; area names are real.
Pool size means passenger BOOKINGS, while fare allocation uses occupied seats.
"""
import argparse
import hashlib
import json
import math
import random
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DEMO_DATE = "2026-10-09"
AREA_ROWS = {
    "DEL": [
        ("Gurugram Cyber City",28.4949,77.0895,18,17,35,"gurugram"),
        ("Udyog Vihar",28.5015,77.0810,12,16,32,"gurugram"),
        ("DLF Phase 3",28.4920,77.0980,10,18,38,"gurugram"),
        ("Golf Course Road",28.4410,77.1030,10,26,50,"gurugram"),
        ("Sohna Road",28.4120,77.0400,8,32,60,"gurugram"),
        ("Dwarka Sector 21",28.5520,77.0580,9,12,25,"dwarka"),
        ("Dwarka Sector 12",28.5920,77.0400,7,18,38,"dwarka"),
        ("Vasant Kunj",28.5200,77.1580,8,12,30,"south"),
        ("Saket",28.5245,77.2066,6,20,45,"south"),
        ("Connaught Place",28.6315,77.2167,7,24,50,"central"),
        ("Karol Bagh",28.6514,77.1907,3,25,55,"central"),
        ("Noida Sector 18",28.5708,77.3210,2,40,75,"noida"),
    ],
    "BOM": [
        ("Andheri East",19.1150,72.8720,16,5,20,"east"),
        ("Powai",19.1197,72.9051,14,9,30,"east"),
        ("Bandra Kurla Complex",19.0607,72.8680,16,9,30,"south"),
        ("Bandra West",19.0596,72.8295,12,11,35,"south"),
        ("Juhu",19.1075,72.8263,9,8,30,"west"),
        ("Goregaon East",19.1646,72.8731,8,12,35,"north"),
        ("Malad West",19.1860,72.8480,6,17,45,"north"),
        ("Borivali West",19.2300,72.8567,5,22,55,"north"),
        ("Dadar",19.0180,72.8437,5,16,45,"south"),
        ("Lower Parel",18.9980,72.8300,4,20,55,"south"),
        ("Colaba",18.9067,72.8147,2,29,70,"south"),
        ("Vashi",19.0771,72.9988,3,28,65,"navi"),
    ],
    "BLR": [
        ("Hebbal",13.0358,77.5970,16,29,40,"north"),
        ("Yelahanka",13.1007,77.5963,12,22,30,"north"),
        ("Manyata Tech Park",13.0480,77.6200,14,30,45,"north"),
        ("Hennur",13.0350,77.6390,8,31,45,"east"),
        ("Indiranagar",12.9784,77.6408,10,39,60,"east"),
        ("Whitefield",12.9698,77.7500,10,45,75,"whitefield"),
        ("Marathahalli",12.9591,77.6974,7,46,75,"whitefield"),
        ("MG Road",12.9756,77.6067,7,36,55,"central"),
        ("Koramangala",12.9352,77.6245,6,43,70,"south"),
        ("HSR Layout",12.9116,77.6389,4,48,80,"south"),
        ("Electronic City",12.8399,77.6770,3,58,95,"south"),
        ("Jayanagar",12.9250,77.5938,3,44,70,"south"),
    ],
}
SPECS = {
    "DEL": ("Indira Gandhi International Airport",28.5562,77.1000,["T1","T2","T3"],"T3",150,48,"DL"),
    "BOM": ("Chhatrapati Shivaji Maharaj International Airport",19.0896,72.8656,["T1","T2"],"T2",120,40,"MH"),
    "BLR": ("Kempegowda International Airport",13.1986,77.7066,["T1","T2"],"T1",150,30,"KA"),
}


def money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def stamp(value):
    return value.isoformat(timespec="minutes")


def parse(value):
    return datetime.fromisoformat(value)


def airports():
    result = []
    for code, spec in SPECS.items():
        name, lat, lng, terminals, reference, base, rate, _ = spec
        areas = [dict(id=f"{code}-A{i+1:02}", name=r[0], lat=r[1], lng=r[2],
                      popularity=r[3], road_km=r[4], day_fare=money(base+rate*r[4]),
                      drive_min=r[5], corridor=r[6]) for i,r in enumerate(AREA_ROWS[code])]
        result.append(dict(code=code,name=name,lat=lat,lng=lng,terminals=terminals,
                           road_reference_terminal=reference,base_fare=base,per_km=rate,
                           dropoff_areas=areas))
    return result


def flights(rng, hubs, day):
    result = []
    for hub in hubs:
        delayed = set(rng.sample(range(16),5))
        for i in range(16):
            # Four waves with four flights each; last scheduled arrival is 23:36.
            scheduled = parse(day+"T20:00+05:30") + timedelta(minutes=(i//4)*65+(i%4)*7)
            delay = rng.choice([10,25,40,70]) if i in delayed else 0
            airline = ["6E","AI","QP","IX","SG"][i%5]
            result.append(dict(id=f"{day}-{hub['code']}-F{i+1:02}",airport=hub['code'],
                terminal=rng.choice(hub['terminals']),airline_code=airline,
                flight_number=f"{airline}{100+i+100*list(SPECS).index(hub['code'])}",
                scheduled_landing=stamp(scheduled),delay_min=delay,
                estimated_landing=stamp(scheduled+timedelta(minutes=delay))))
    return result


def passengers(rng, hubs, arrivals, day):
    result = []
    for hub in hubs:
        available = [f for f in arrivals if f['airport']==hub['code']]
        areas = hub['dropoff_areas']
        for i in range(70):
            flight = rng.choice(available)
            area = rng.choices(areas,weights=[a['popularity'] for a in areas])[0]
            gender = rng.choices(['woman','man','nonbinary'],[48,50,2])[0]
            bags = rng.choices([0,1,2,3],[35,40,20,5])[0]
            result.append(dict(id=f"{day}-{hub['code']}-P{i+1:03}",airport=hub['code'],
                terminal=flight['terminal'],flight_id=flight['id'],gender=gender,
                party_size=rng.choices([1,2,3],[75,20,5])[0],large_bags=bags,
                women_only=gender=='woman' and rng.random()<0.25,
                party_all_women=gender=='woman',
                max_wait_min=rng.choice([15,30,45]),dropoff_area_id=area['id'],
                ready_time=stamp(parse(flight['estimated_landing'])+timedelta(minutes=22 if bags else 12))))
    return result


def drivers(rng):
    result = []
    for code,spec in SPECS.items():
        for i in range(14):
            suv = i%4==0
            # Synthetic registration identifiers, not real vehicles.
            plate = f"{spec[7]} {rng.choice(['01','02','03','04'])} {chr(65+i)}{chr(65+list(SPECS).index(code))} {1000+i:04}"
            result.append(dict(id=f"{code}-D{i+1:02}",airport=code,vehicle_type='SUV' if suv else 'sedan',
                               seats=6 if suv else 4,bag_capacity=6 if suv else 4,plate=plate))
    return result


def separation(a,b):
    lat1,lat2 = math.radians(a['lat']),math.radians(b['lat'])
    dlat,dlng = lat2-lat1,math.radians(b['lng']-a['lng'])
    return 6371*2*math.asin(min(1,math.sqrt(math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2)))


def fits(group, candidate, areas, seats, bags):
    members = group+[candidate]
    if any(p['airport']!=candidate['airport'] or p['terminal']!=candidate['terminal'] for p in group):
        return False
    if sum(p['party_size'] for p in members)>seats or sum(p['large_bags'] for p in members)>bags:
        return False
    if any(p['women_only'] for p in members) and not all(p['gender']=='woman' and p['party_all_women'] for p in members):
        return False
    departure = max(parse(p['ready_time']) for p in members)
    if any((departure-parse(p['ready_time'])).total_seconds()>p['max_wait_min']*60 for p in members):
        return False
    dest = areas[candidate['dropoff_area_id']]
    return all(areas[p['dropoff_area_id']]['corridor']==dest['corridor'] and
               separation(areas[p['dropoff_area_id']],dest)<=5 for p in group)


def match(bookings, areas, seats=4, bags=4):
    """Deterministic first-fit matcher; demo heuristic, not global optimization."""
    groups = []
    for p in sorted(bookings,key=lambda p:(p['ready_time'],p['id'])):
        for group in groups:
            if fits(group,p,areas,seats,bags):
                group.append(p)
                break
        else:
            groups.append([p])
    return groups


def fare(area, departure):
    # Night window crosses midnight; day tariff resumes at 06:00.
    return money(area['day_fare']*(1.2 if departure.hour>=22 or departure.hour<6 else 1))


def trip(group, areas, trip_id, driver=None):
    departure = max(parse(p['ready_time']) for p in group)
    solo = [fare(areas[p['dropoff_area_id']],departure) for p in group]
    total = money(max(solo)*(1.15 if len(group)>1 else 1))
    occupied = sum(p['party_size'] for p in group)
    # Integer paise allocation makes the shares sum exactly to the cab fare.
    paise = int(Decimal(str(total))*100)
    shares = [paise*p['party_size']//occupied for p in group]
    residual = paise-sum(shares)
    for i in range(residual):
        shares[i%len(shares)] += 1
    return dict(id=trip_id,airport=group[0]['airport'],terminal=group[0]['terminal'],
        driver_id=driver['id'] if driver else None,departure_time=stamp(departure),
        passenger_ids=[p['id'] for p in group],pool_size=len(group),occupied_seats=occupied,
        large_bags=sum(p['large_bags'] for p in group),shared=len(group)>1,total_fare=total,
        fare_per_seat=money(total/occupied),allocations=[dict(passenger_id=p['id'],
        party_size=p['party_size'],solo_fare=solo[i],fare=shares[i]/100) for i,p in enumerate(group)])


def scenarios(areas):
    def p(i,area='DEL-A01',**kw):
        row=dict(id=f"S{i}",airport='DEL',terminal='T3',gender='woman',party_all_women=True,
                 party_size=1,large_bags=0,women_only=False,max_wait_min=15,
                 ready_time=DEMO_DATE+'T22:12+05:30',dropoff_area_id=area)
        row.update(kw)
        return row
    cases = [
        ('perfect_trio',[p(1),p(2),p(3)],[3]),
        ('nearby_dropoffs',[p(1),p(2,'DEL-A02')],[2]),
        ('luggage_overflow',[p(1,large_bags=2),p(2,large_bags=2),p(3,large_bags=1)],[2,1]),
        ('women_only_pool',[p(1,women_only=True),p(2),p(3,gender='man',party_all_women=False)],[2,1]),
        ('delayed_flight_breaks_match',[p(1),p(2,ready_time=DEMO_DATE+'T22:52+05:30')],[1,1]),
        ('opposite_directions',[p(1),p(2,'DEL-A10')],[1,1]),
        ('party_of_three_fills_cab',[p(1,party_size=3),p(2),p(3)],[2,1]),
    ]
    result=[]
    for name,bookings,expected in cases:
        groups=match(bookings,areas)
        actual=[len(g) for g in groups]
        assert actual==expected, (name,actual,expected)
        result.append(dict(name=name,passengers=bookings,vehicle=dict(seats=4,bag_capacity=4),
                           expected_pool_sizes=expected,actual_pool_sizes=actual,passed=True))
    return result


def validate(data):
    hubs=data['airports']; fs=data['flights']; ps=data['passengers']; ds=data['drivers']
    areas={a['id']:a for h in hubs for a in h['dropoff_areas']}
    assert len(hubs)==3 and len(fs)==48 and len(ps)==210 and len(ds)==42
    assert Counter(f['airport'] for f in fs)==dict.fromkeys(SPECS,16)
    assert Counter(p['airport'] for p in ps)==dict.fromkeys(SPECS,70)
    assert Counter(d['airport'] for d in ds)==dict.fromkeys(SPECS,14)
    for h in hubs:
        assert 10<=len(h['dropoff_areas'])<=12
        assert sum(a['popularity'] for a in h['dropoff_areas'])==100
        for a in h['dropoff_areas']:
            assert a['day_fare']==money(h['base_fare']+h['per_km']*a['road_km'])
    assert fare(areas['DEL-A01'],parse(DEMO_DATE+'T22:00+05:30'))==1159.2
    flight_map={f['id']:f for f in fs}
    for p in ps:
        assert not p['women_only'] or p['gender']=='woman'
        assert p['ready_time']==stamp(parse(flight_map[p['flight_id']]['estimated_landing'])+timedelta(minutes=22 if p['large_bags'] else 12))
        assert p['party_size'] in [1,2,3] and 0<=p['large_bags']<=3 and p['max_wait_min'] in [15,30,45]
    assert len(data['trip_history'])==14
    driver_map={d['id']:d for d in ds}
    for day in [dict(date=DEMO_DATE,passengers=ps,trips=data['demo_trips'])]+data['trip_history']:
        lookup={p['id']:p for p in day['passengers']}
        seen=[]
        for t in day['trips']:
            group=[lookup[i] for i in t['passenger_ids']]
            seen.extend(t['passenger_ids'])
            driver=driver_map[t['driver_id']]
            assert t['occupied_seats']<=driver['seats'] and t['large_bags']<=driver['bag_capacity']
            for i,p in enumerate(group):
                assert fits(group[:i],p,areas,driver['seats'],driver['bag_capacity'])
            assert t==trip(group,areas,t['id'],driver)
            assert sum(int(round(a['fare']*100)) for a in t['allocations'])==int(round(t['total_fare']*100))
        assert sorted(seen)==sorted(lookup)
    all_trips=[t for day in data['trip_history'] for t in day['trips']]
    def stats(trips):
        return dict(trips=len(trips),solo_trip_share=round(sum(t['pool_size']==1 for t in trips)/len(trips),6),
                    pool_size_distribution=dict(sorted(Counter(t['pool_size'] for t in trips).items())),
                    cab_fare_range=[min(t['total_fare'] for t in trips),max(t['total_fare'] for t in trips)],
                    per_seat_fare_range=[min(t['fare_per_seat'] for t in trips),max(t['fare_per_seat'] for t in trips)])
    return dict(airports=len(hubs),areas=len(areas),flights=len(fs),delayed_flights=sum(f['delay_min']>0 for f in fs),
                passengers=len(ps),drivers=len(ds),history_days=14,history_passenger_bookings=14*210,
                scenarios_passed=7,day_fare_range=[min(a['day_fare'] for a in areas.values()),max(a['day_fare'] for a in areas.values())],
                demo=stats(data['demo_trips']),history=stats(all_trips))


def generate(seed):
    rng=random.Random(seed); hubs=airports(); ds=drivers(rng)
    areas={a['id']:a for h in hubs for a in h['dropoff_areas']}
    def make_day(day):
        fs=flights(rng,hubs,day); ps=passengers(rng,hubs,fs,day); ts=[]
        for code in SPECS:
            # Conservative sedan pools can be served by either vehicle class.
            fleet=[d for d in ds if d['airport']==code]
            for i,g in enumerate(match([p for p in ps if p['airport']==code],areas)):
                ts.append(trip(g,areas,f"{day}-{code}-R{i+1:03}",fleet[i%len(fleet)]))
        return dict(date=day,flights=fs,passengers=ps,trips=ts)
    current=make_day(DEMO_DATE)
    history=[make_day((datetime.fromisoformat(DEMO_DATE)-timedelta(days=i)).date().isoformat()) for i in range(14,0,-1)]
    data=dict(metadata=dict(schema_version='1.0',seed=seed,demo_date=DEMO_DATE,currency='INR',timezone='Asia/Kolkata',
        synthetic=True,night_window='22:00-06:00',night_multiplier=1.2,shared_detour_multiplier=1.15,
        pool_size_unit='bookings',fare_split_unit='occupied seats',
        notes=['Road km and drive minutes are hand-set estimates from each reference terminal; no terminal-specific route adjustment.',
               'Popularity is a synthetic percentage weight, not measured demand.',
               'Scheduled arrivals occur before midnight; delayed arrivals and ready times may cross into the next day.',
               'Women-only assumes all companions in a woman-led booking are women; party_all_women makes this explicit.',
               'Greedy matching requires same terminal, same corridor, pairwise drop-offs within 5 km, capacity and all wait limits.',
               'Solo fare is per cab and evaluated at pool departure time. Shared total is max member solo fare times 1.15.',
               'A solo booking with multiple people pays one cab fare, split internally by seats.',
               'Driver assignment is illustrative cyclic allocation, not an availability or dispatch simulation.',
               'History is 14 complete synthetic daily cohorts of 210 bookings each.'],
        distance_context_sources=['https://www.delhiairporthotel.com/delhi-airport-to-gurugram-cyber-city/',
            'https://ksiidc.com/kannada/assets/pdf/tenders/works/4.-BICC-PIM-Annexure-I.pdf']),
        airports=hubs,flights=current['flights'],passengers=current['passengers'],drivers=ds,
        demo_trips=current['trips'],trip_history=history,scenario_tests=scenarios(areas))
    data['validation_report']=validate(data)
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=int,default=20261009)
    parser.add_argument('--output',type=Path,default=Path(__file__).with_name('airpool_demo_data.json'))
    args=parser.parse_args()
    data=generate(args.seed)
    payload=json.dumps(data,indent=2,ensure_ascii=False)+'\n'
    assert payload==json.dumps(generate(args.seed),indent=2,ensure_ascii=False)+'\n', 'Reproducibility failed'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(payload,encoding='utf-8')
    print(json.dumps(data['validation_report'],indent=2))
    print('All 7 scenarios passed; reproducibility and structural checks passed.')
    print(f'Output: {args.output.resolve()}')
    print(f'SHA256: {hashlib.sha256(payload.encode()).hexdigest()}')


if __name__=='__main__':
    main()
