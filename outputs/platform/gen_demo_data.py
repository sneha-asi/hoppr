"""Seeded v2 data. Run before building any UI. Names and operational data fictional."""
import argparse
import hashlib
import importlib.util
import json
import random
import sys
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from matcher import Rider,match_riders,quote_fare,compatible,fits_cab
from store import RELATIONS,save_dataset
spec=importlib.util.spec_from_file_location('legacy_demo',Path(__file__).resolve().parents[1]/'gen_demo_data.py')
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
NOW=datetime.fromisoformat('2026-10-09T20:00:00+05:30')
FIRST=['Aarav','Aisha','Meera','Kabir','Zoya','Arjun','Fatima','Ishaan','Ananya','Dev','Gurpreet','Nandini','Rehan','Lakshmi','Tenzin','Riya','Aditya','Mary','Sana','Rohan','Sandeep','Amrita','Harpreet','Joseph']
PERSONAS=['Frequent business flyer','Student with two bags','Family of three','Solo woman','Repeat commuter','First-time traveller','Corporate traveller','Elderly traveller','Changes plans often','Dispute in progress','Quiet ride preferred','Accessible journey requested']

def ts(t):return t.isoformat(timespec='seconds')
def paise(value):return int((Decimal(str(value))*100).quantize(Decimal('1')))
def generate(seed=20261009):
    rng=random.Random(seed); data={k:[] for k in RELATIONS}
    data['metadata']={'schema_version':2,'seed':seed,'synthetic':True,'clock':ts(NOW),'currency':'INR','money_unit':'paise','timezone':'Asia/Kolkata','driver_share':0.8,'platform_fee_per_seat':1900,'illustrative_gst_rate':0.05,'solo_cap':250000,'notes':['Hand-set routes, pickup bays, fares, tax and demand. Not live tariffs.','60-day archived flights support booking references; visible board is last 14 plus next 3 days.','Sedan matching capacity applies to SUVs too. Mock verification badges are synthetic.','All contact, payment, document and geofence actions are simulations.']}
    for hub in legacy.airports():
        hub['id']=hub['code'];hub['pickup_points']=[{'terminal':t,'label':f'{t} demo meeting zone','walking_directions':['Follow the Arrivals signs after baggage collection.','Confirm the authorised cab meeting point with airport staff and your driver.','The illustrated bay is not a verified airport instruction.'],'verified':False} for t in hub['terminals']]
        data['airports'].append(hub)
    hubs={h['id']:h for h in data['airports']};areas={a['id']:a for h in hubs.values() for a in h['dropoff_areas']}
    for i in range(800):
        airport=list(hubs)[i%3];gender='woman' if i%2==0 else 'man';persona=PERSONAS[i%12]
        data['riders'].append({'id':f'R{i+1:04}','first_name':'Meera' if i==0 else FIRST[i%len(FIRST)],'email':'demo@hoppr.app' if i==0 else f'rider{i+1}@example.invalid','airport_id':airport,'gender':gender,'persona':persona,'demo':True,'verified':i%7!=0,'rating':round(rng.uniform(3.8,5),1),'saved_places':[{'label':'Home','destination':hubs[airport]['dropoff_areas'][i%12]['id']},{'label':'Office','destination':hubs[airport]['dropoff_areas'][(i+2)%12]['id']}],'preferences':{'quiet':i%4==0,'women_only':gender=='woman' and i%8==0,'accessibility':i%12==7,'child_seat':i%12==2,'max_wait':rng.choice([15,30,45])},'language':'hi' if i>0 and i%6==0 else 'en','referral_code':f'HOPPR{i+101:X}','notification_settings':{'flight':True,'trip':True,'offers':False},'privacy':{'analytics':False}})
    for i in range(120):
        airport=list(hubs)[i%3];status='approved' if i<108 else rng.choice(['pending','documents_needed']);driver_id=f'D{i+1:03}'
        docs=[{'type':name,'status':'expiring' if i%13==0 and j==1 else 'approved' if status=='approved' else 'pending','expires':(NOW+timedelta(days=9 if i%13==0 and j==1 else 110+i+j)).date().isoformat(),'file':'Synthetic document placeholder — no personal document'} for j,name in enumerate(['Licence','RC','Insurance','Permit','Police verification'])]
        data['drivers'].append({'id':driver_id,'airport_id':airport,'first_name':FIRST[(i+3)%len(FIRST)],'demo':True,'status':status,'online':status=='approved' and i%5!=0,'documents':docs,'rating':round(rng.uniform(3.9,5),1),'acceptance_rate':rng.randint(76,98),'cancellation_rate':rng.randint(0,6),'payout_mask':'Demo account •••• '+f'{i+2000}','shift':'18:00–02:00','language':'en','queue_position':i//3+1,'geofence':'simulated_inside','incentive_target':8,'incentive_bonus':50000})
        suv=i%4==0
        data['cabs'].append({'id':f'C{i+1:03}','driver_id':driver_id,'airport_id':airport,'kind':'SUV' if suv else 'Sedan','seats':6 if suv else 4,'bags':6 if suv else 4,'plate':f'{legacy.SPECS[airport][-1]} {i%9+1:02} DM {4100+i}','demo':True,'insurance_expiry':docs[2]['expires']})
    # 60 history dates plus today and next two dates; arrivals visible from last14 days onward.
    for offset in range(-60,3):
        day=(NOW+timedelta(days=offset)).replace(hour=20,minute=0,second=0)
        for airport,hub in hubs.items():
            for j in range(25):
                scheduled=day+timedelta(minutes=(j//5)*44+(j%5)*6)
                # Synthetic season/weather patterns, explicitly not observations.
                delay=rng.choices([0,10,25,40,70],[70 if airport!='BOM' else 65,9,10,7,4])[0]
                eta=scheduled+timedelta(minutes=delay);fid=f'{day:%Y%m%d}-{airport}-{j+1:02}'
                airline=['6E','AI','QP','IX','SG'][j%5]
                data['flights'].append({'id':fid,'airport_id':airport,'airport':airport,'flight_no':airline+str(410+j),'airline':airline,'origin':['HYD','CCU','MAA','GOI','AMD'][j%5],'terminal':hub['terminals'][j%len(hub['terminals'])],'scheduled':ts(scheduled),'estimated':ts(eta),'delay_min':delay,'status':'delayed' if delay else 'scheduled','source':'demo','baggage_belt':str(2+j%8),'visible':offset>=-14,'date':day.date().isoformat()})
                for k,minutes in enumerate([0,delay//2,delay]):
                    data['flight_updates'].append({'id':fid+f'-U{k}','flight_id':fid,'observed_at':ts(scheduled-timedelta(minutes=100-k*35)),'estimated':ts(scheduled+timedelta(minutes=minutes)),'reason':'Synthetic monsoon pattern' if delay and airport=='BOM' else 'Synthetic operational update'})
    flights_by_day=defaultdict(list)
    for f in data['flights']:flights_by_day[(f['date'],f['airport_id'])].append(f)
    riders_by_airport={a:[r for r in data['riders'] if r['airport_id']==a] for a in hubs}
    driver_availability={}; pool_number=0
    for offset in range(-60,0):
        day=NOW+timedelta(days=offset);boost=1.18 if day.weekday() in (4,6) else 1
        if day.date().isoformat()=='2026-09-25':boost*=1.12 # Synthetic festival-demand example, not a calendar assertion.
        for airport,hub in hubs.items():
            cohort=[];mapping={};fs=flights_by_day[(day.date().isoformat(),airport)]
            selected=rng.sample(riders_by_airport[airport],int(rng.randint(61,72)*boost))
            for i,r in enumerate(selected):
                f=rng.choices(fs,[9 if 15<=j<20 else 1 for j in range(25)])[0];area=rng.choices(hub['dropoff_areas'],[a['popularity'] for a in hub['dropoff_areas']])[0]
                party=3 if r['persona']=='Family of three' else rng.choices([1,2],[88,12])[0]
                bags=2 if r['persona']=='Student with two bags' else rng.choices([0,1,2,3],[45,38,13,4])[0]
                ready=datetime.fromisoformat(f['estimated'])+timedelta(minutes=22 if bags else 12)
                solo=Decimal(str(area['day_fare']))*(Decimal('1.2') if ready.hour>=22 or ready.hour<6 else 1)
                bid=f'B{offset+60:02}{airport}{i:03}'
                candidate=Rider(bid,ready,r['preferences']['max_wait'],area['lat'],area['lng'],r['gender'],party,bags,r['preferences']['women_only'],solo,f['id'])
                cohort.append(candidate);mapping[bid]=(r,f,area)
            # Partition terminal pickup, then run the actual pure matcher.
            for terminal in hub['terminals']:
                for group in match_riders([r for r in cohort if mapping[r.id][1]['terminal']==terminal]):
                    pool_number+=1;pid=f'P{pool_number:06}';pickup=max(r.ready_time for r in group)
                    fleet=[d for d in data['drivers'] if d['airport_id']==airport and d['status']=='approved']
                    available=[d for d in fleet if driver_availability.get(d['id'],pickup)<=pickup]
                    if not available:raise AssertionError('Need more resting drivers for this synthetic cohort')
                    driver=rng.choice(available);cab=data['cabs'][int(driver['id'][1:])-1]
                    end=pickup+timedelta(minutes=max(mapping[r.id][2]['drive_min'] for r in group)+5*(len(group)-1))
                    driver_availability[driver['id']]=end+timedelta(minutes=15)
                    cancelled=rng.random()<.04;status='cancelled' if cancelled else 'completed'
                    quote=quote_fare(group);p={'id':pid,'airport_id':airport,'terminal':terminal,'driver_id':driver['id'],'cab_id':cab['id'],'booking_ids':[r.id for r in group],'pickup':ts(pickup),'end':ts(end),'status':status,'date':day.date().isoformat(),'road_km':max(mapping[r.id][2]['road_km'] for r in group),'seats':sum(r.party_size for r in group),'bags':sum(r.large_bags for r in group),'events':[{'at':ts(pickup-timedelta(minutes=10)),'text':'Matched by greedy algorithm'},{'at':ts(pickup),'text':'Cancelled before pickup' if cancelled else 'Pickup code verified'},{'at':ts(end),'text':status}],'edge_case':rng.choices(['normal','late_join','no_show','delay_rematch'],[88,4,3,5])[0]}
                    data['pools'].append(p)
                    for member in group:
                        r,f,area=mapping[member.id];transport=paise(quote.fare_per_seat*member.party_size);service=1900*member.party_size;tax=(transport+service+10)//20;gross=transport+service+tax;tip=0 if cancelled else rng.choices([0,2000,5000],[90,7,3])[0]
                        payout=transport*80//100+tip;platform=transport-transport*80//100+service
                        payment={'id':'PAY-'+member.id,'booking_id':member.id,'transport':transport,'service_fee':service,'platform_fee':0 if cancelled else platform,'tax':0 if cancelled else tax,'gross':gross+tip,'tip':tip,'refund':gross+tip if cancelled else 0,'driver_payout':0 if cancelled else payout,'driver_deduction':payout if cancelled else 0,'method':rng.choice(['upi','card','wallet']),'wallet_applied':min(gross,15000) if rng.random()<.24 else 0,'promo_applied':min(gross,5000) if rng.random()<.05 else 0,'date':p['date'],'receipt_no':'DEMO-'+member.id,'tax_label':'Illustrative GST 5%; not a tax invoice'}
                        payment['net']=payment['gross']-payment['refund']
                        b={'id':member.id,'rider_id':r['id'],'flight_id':f['id'],'pool_id':pid,'driver_id':driver['id'],'cab_id':cab['id'],'destination':area['id'],'ready_time':ts(member.ready_time),'pickup':ts(pickup),'party':member.party_size,'bags':member.large_bags,'max_wait':member.max_wait_min,'women_only':member.women_only,'gender':r['gender'],'solo_fare':paise(member.solo_fare),'locked_transport':transport,'status':status,'ride_type':'pool','pickup_code':f'{rng.randint(1000,9999)}','demo':True,'no_show':p['edge_case']=='no_show' and member==group[-1]}
                        data['bookings'].append(b);data['payments'].append(payment)
                        if payment['wallet_applied']:data['wallet_entries'].append({'id':'W-'+member.id,'rider_id':r['id'],'booking_id':member.id,'amount':-payment['wallet_applied'],'reason':'Wallet tender','at':ts(pickup-timedelta(minutes=5))})
                        if cancelled:data['wallet_entries'].append({'id':'REF-'+member.id,'rider_id':r['id'],'booking_id':member.id,'amount':payment['refund'],'reason':'Cancellation refund','at':ts(pickup)})
                        if not cancelled:
                            for direction in ['rider_to_driver','driver_to_rider']:
                                data['ratings'].append({'id':member.id+'-'+direction,'booking_id':member.id,'direction':direction,'score':rng.choices([3,4,5],[5,27,68])[0],'text':rng.choice(['Clear pickup instructions','Comfortable ride','A little waiting at the terminal','Helpful with luggage']),'tip':tip if direction=='rider_to_driver' else 0})
    # Prefund wallet so synthetic debits never create negative balances; all credits disclosed.
    debits=Counter()
    for w in data['wallet_entries']:
        if w['amount']<0:debits[w['rider_id']]-=w['amount']
    data['wallet_entries'][:0]=[{'id':'OPEN-'+r['id'],'rider_id':r['id'],'booking_id':None,'amount':debits[r['id']]+15000,'reason':'Synthetic opening credit','at':ts(NOW-timedelta(days=61))} for r in data['riders']]
    for i in range(300):
        b=rng.choice(data['bookings']);created=NOW-timedelta(hours=rng.randint(1,1000));category=['Pickup','Refund','Lost item','Fare question','Dispute'][i%5]
        data['tickets'].append({'id':f'T{i+1:04}','rider_id':b['rider_id'],'booking_id':b['id'],'category':category,'status':'open' if i<28 else 'resolved','created_at':ts(created),'sla_due':ts(created+timedelta(hours=24)),'thread':[{'by':'rider','text':f'Demo {category.lower()} request. Please review my ride.','at':ts(created)},{'by':'support','text':'Synthetic case reviewed; no external message sent.','at':ts(created+timedelta(hours=1))}]})
    for i in range(25):
        p=rng.choice(data['pools']);data['incidents'].append({'id':f'I{i+1:03}','pool_id':p['id'],'severity':'medium' if i%8==0 else 'low','kind':['Pickup confusion','Route question','Lost item','Rider concern'][i%4],'status':'open' if i<4 else 'resolved','notes':'Synthetic incident. No real emergency service contacted.','created_at':p['pickup']})
    for i in range(6):data['ops_users'].append({'id':f'O{i+1}','first_name':FIRST[i+5],'role':['admin','ops_lead','support','finance','support','ops_lead'][i],'demo':True})
    for i in range(90):data['audit'].append({'id':f'A{i+1:04}','ops_user_id':f'O{i%6+1}','action':['review_ticket','approve_document','reconcile_day'][i%3],'entity_id':data['tickets'][i]['id'],'at':ts(NOW-timedelta(hours=90-i))})
    data['promos']=[{'id':'WELCOME50','discount':5000,'active':True},{'id':'FLIGHTMATES','discount':7500,'active':True}]
    for i in range(90):data['passes'].append({'id':f'PASS{i:03}','rider_id':data['riders'][i]['id'],'kind':'weekly' if i%2 else 'monthly','price':99000 if i%2 else 299000,'status':'demo','free_cancellation':True})
    for i in range(100):data['referrals'].append({'id':f'REFERRAL{i:03}','rider_id':data['riders'][i]['id'],'referred_rider_id':data['riders'][i+120]['id'],'credit':2500,'status':'pending'})
    for i in range(45):data['demand_requests'].append({'id':f'REQ{i:03}','rider_id':data['riders'][i]['id'],'airport':['DEL','BOM','BLR'][i%3],'area':'Synthetic requested corridor '+str(i+1),'status':'received'})
    return data

def validate(data):
    indices={k:{r['id']:r for r in data[k]} for k in RELATIONS}; errors=[];checks={}
    def check(name,condition):
        checks[name]='PASS' if condition else 'FAIL'
        if not condition:errors.append(name)
    relation_ok=True
    for table,refs in RELATIONS.items():
        for row in data[table]:
            for key,target in refs.items():
                if row.get(key) is not None and row[key] not in indices[target]:relation_ok=False
    agree=relation_ok and all(b['driver_id']==indices['pools'][b['pool_id']]['driver_id'] and b['cab_id']==indices['pools'][b['pool_id']]['cab_id'] and b['id'] in indices['pools'][b['pool_id']]['booking_ids'] and indices['flights'][b['flight_id']]['airport_id']==indices['pools'][b['pool_id']]['airport_id'] and indices['flights'][b['flight_id']]['terminal']==indices['pools'][b['pool_id']]['terminal'] and b['gender']==indices['riders'][b['rider_id']]['gender'] and b['pickup']==indices['pools'][b['pool_id']]['pickup'] for b in data['bookings'])
    pool_agree=relation_ok and all(indices['cabs'][p['cab_id']]['driver_id']==p['driver_id'] and indices['drivers'][p['driver_id']]['airport_id']==p['airport_id']==indices['cabs'][p['cab_id']]['airport_id'] for p in data['pools'])
    payment_refs=[p['booking_id'] for p in data['payments']]
    check('1_foreign_keys_and_booking_agreement',relation_ok and agree and pool_agree and len(set(payment_refs))==len(data['bookings']) and set(payment_refs)==set(indices['bookings']))
    if not relation_ok or not pool_agree:raise AssertionError('1_foreign_keys_and_booking_agreement FAIL')
    capacity=True;women=True;pairwise=True
    areas={a['id']:a for h in data['airports'] for a in h['dropoff_areas']}
    for p in data['pools']:
        bs=[indices['bookings'][i] for i in p['booking_ids']]
        capacity &= sum(b['party'] for b in bs)<=4 and sum(b['bags'] for b in bs)<=4 and p['seats']==sum(b['party'] for b in bs) and p['bags']==sum(b['bags'] for b in bs)
        capacity &= all(datetime.fromisoformat(b['pickup'])>=datetime.fromisoformat(indices['flights'][b['flight_id']]['estimated'])+timedelta(minutes=22 if b['bags'] else 12) for b in bs)
        capacity &= all(datetime.fromisoformat(b['ready_time'])==datetime.fromisoformat(indices['flights'][b['flight_id']]['estimated'])+timedelta(minutes=22 if b['bags'] else 12) for b in bs)
        women &= not any(b['women_only'] for b in bs) or all(b['gender']=='woman' for b in bs)
        rr=[Rider(b['id'],datetime.fromisoformat(b['ready_time']),b['max_wait'],areas[b['destination']]['lat'],areas[b['destination']]['lng'],b['gender'],b['party'],b['bags'],b['women_only']) for b in bs]
        pairwise &= all(compatible(a,b) for i,a in enumerate(rr) for b in rr[i+1:])
    check('2_capacity_ready_time_pairwise',capacity and pairwise)
    check('3_money_reconciles_trip_and_day',all(p['net']==p['driver_payout']+p['platform_fee']+p['tax'] for p in data['payments']))
    payments_by_booking={p['booking_id']:p for p in data['payments']}
    driver_total=Counter();trip_total=Counter()
    for b in data['bookings']:
        money=payments_by_booking[b['id']];driver_total[b['driver_id']]+=money['driver_payout'];trip_total[b['pool_id']]+=money['driver_payout']
    check('4_driver_and_ops_totals',sum(driver_total.values())==sum(trip_total.values())==sum(p['driver_payout'] for p in data['payments']))
    refunds={w['booking_id']:w['amount'] for w in data['wallet_entries'] if w['reason']=='Cancellation refund'}
    check('5_receipts_refunds_and_deductions',all(p['net']==p['gross']-p['refund'] and (not p['refund'] or refunds.get(p['booking_id'])==p['refund'] and p['driver_payout']==0 and p['driver_deduction']>0) for p in data['payments']))
    check('6_histories_share_trip_ids',set(b['pool_id'] for b in data['bookings'])==set(indices['pools']) and all(b['id'] in indices['pools'][b['pool_id']]['booking_ids'] for b in data['bookings']))
    overlap=False
    for d in data['drivers']:
        trips=sorted([p for p in data['pools'] if p['driver_id']==d['id']],key=lambda p:p['pickup'])
        overlap |= any(datetime.fromisoformat(a['end'])+timedelta(minutes=15)>datetime.fromisoformat(b['pickup']) for a,b in zip(trips,trips[1:]))
    unique=Counter((b['rider_id'],b['flight_id']) for b in data['bookings'])
    check('7_no_double_assignment_with_rest',not overlap and all(n==1 for n in unique.values()))
    check('8_women_ratings_cancelled_payout',women and all(1<=r['score']<=5 for r in data['ratings']) and all(payments_by_booking[b['id']]['driver_payout']==0 for b in data['bookings'] if b['status']=='cancelled'))
    # Use the original explicit scenarios, but run the new shared pure matcher.
    scenario_rows=legacy.scenarios(areas)
    scenario_ok=True
    for s in scenario_rows:
        raw=s['passengers'] if 'passengers' in s else s.get('riders',[])
        if not raw:continue
        from matcher import rider_from_demo
        groups=match_riders([rider_from_demo(r,areas) for r in raw])
        expected=s.get('expected_pool_sizes',s.get('expected_sizes'))
        if expected is not None:scenario_ok &= sorted(map(len,groups))==sorted(expected)
    check('9_seven_scenarios',scenario_ok and len(scenario_rows)==7)
    sizes=Counter(len(p['booking_ids']) for p in data['pools']);byhour=defaultdict(list);byday=Counter()
    for p in data['pools']:byhour[p['pickup'][11:13]].append(p['seats']/4)
    for p in data['payments']:byday[p['date']]+=p['net']
    report={'counts':{k:len(data[k]) for k in RELATIONS},'fare_range_paise':[min(p['gross'] for p in data['payments']),max(p['gross'] for p in data['payments'])],'solo_share':round(sizes[1]/len(data['pools']),4),'pool_size_distribution':dict(sizes),'fill_rate_by_hour':{h:round(sum(v)/len(v),4) for h,v in sorted(byhour.items())},'revenue_by_day_paise':dict(sorted(byday.items())),'invariants':checks}
    if errors:raise AssertionError(', '.join(errors))
    return report

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--seed',type=int,default=20261009);ap.add_argument('--output',type=Path,default=Path(__file__).with_name('demo_data.json'));ap.add_argument('--db',type=Path,default=Path(__file__).with_name('hoppr.sqlite3'));args=ap.parse_args()
    data=generate(args.seed);report=validate(data);data['validation_report']=report
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n';args.output.write_text(payload,encoding='utf-8');save_dataset(data,args.db)
    Path(__file__).with_name('validation-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));print('SHA256',hashlib.sha256(payload.encode()).hexdigest())

if __name__=='__main__':main()
