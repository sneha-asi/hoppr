"""Hoppr demo API. Run: uvicorn api:app --app-dir outputs --workers 1.

Offline ingest is the default. Set AIRPOOL_OFFLINE=0 to enable the unvalidated
live provider chain. This scaffold has no authentication or payment integration.
"""
import asyncio
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import math
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from flight_ingest import (AeroDataBoxProvider, AirportScraper, DemoProvider,
                          init_db, poll_once)
from matcher import Rider, match_riders, quote_fare, rematch_flight

HERE = Path(__file__).parent
LOG = logging.getLogger(__name__)


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    flight_id: str
    destination: str
    bags: int = Field(ge=0, le=4)
    party: int = Field(ge=1, le=4)
    max_wait: int = Field(ge=0, le=45)
    women_only: bool
    ride_type: Literal['pool','private'] = 'pool'
    # With the six-field request, women_only=true attests that the entire party
    # consists of women. Otherwise gender is unknown, never silently a woman.
    gender: Literal['woman', 'man', 'nonbinary', 'unknown'] | None = None


class BookRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    match_id: str
    quote_version: int = Field(ge=1)
    wallet_id: str = Field(default='demo',min_length=1,max_length=80)
    payment_method: Literal['upi','card','cash'] = 'upi'


class CancelRequest(BaseModel):
    booking_id: str
    wallet_id: str = Field(min_length=1,max_length=80)
    reason: Literal['pool_fell_through','changed_plans'] = 'changed_plans'


class SupportRequest(BaseModel):
    wallet_id: str = Field(min_length=1,max_length=80)
    booking_id: str | None = None
    message: str = Field(min_length=5,max_length=2000)


class StepRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    trip_id: str
    step: Literal['en_route', 'arrived', 'picked_up', 'completed']
    pickup_codes: dict[str, str] | None = None


def uid():
    return uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


class FlightsLimiter:
    """Per-client sliding window shared across airports, in this worker only."""
    def __init__(self,limit,window,clock=time.monotonic):
        if limit<1 or window<=0:
            raise ValueError('Rate limit and window must be positive')
        self.limit=limit;self.window=window;self.clock=clock
        self.lock=threading.Lock();self.clients={};self.last_cleanup=clock()

    def check(self,client):
        with self.lock:
            current=self.clock()
            cutoff=current-self.window
            if current-self.last_cleanup>=self.window:
                for key in list(self.clients):
                    if not self.clients[key] or self.clients[key][-1]<=cutoff:
                        del self.clients[key]
                self.last_cleanup=current
            if client not in self.clients and len(self.clients)>=10000:
                raise HTTPException(429,'Rate limiter capacity reached; retry later',headers={'Retry-After':str(math.ceil(self.window))})
            queue=self.clients.setdefault(client,deque())
            while queue and queue[0]<=cutoff:
                queue.popleft()
            headers={'RateLimit-Limit':str(self.limit),'RateLimit-Remaining':str(max(0,self.limit-len(queue))),
                     'RateLimit-Reset':str(max(1,math.ceil(queue[0]+self.window-current))) if queue else str(math.ceil(self.window))}
            if len(queue)>=self.limit:
                raise HTTPException(429,'Too many flight requests; retry after the window resets',
                                    headers={**headers,'Retry-After':headers['RateLimit-Reset']})
            queue.append(current)
            headers['RateLimit-Remaining']=str(self.limit-len(queue))
            return headers


class Store:
    """Serialized SQLite transactions; only one API worker should poll ingest."""
    def __init__(self, db_path, demo_path, providers, solo_cap=2500,cache_ttl=10,clock=time.monotonic):
        self.db_path = str(db_path)
        self.demo = json.loads(Path(demo_path).read_text(encoding='utf-8'))
        self.areas = {a['id']: dict(a, airport=h['code']) for h in self.demo['airports'] for a in h['dropoff_areas']}
        self.providers = providers
        self.solo_cap = Decimal(str(solo_cap))
        if self.solo_cap < 10:
            raise ValueError('Solo cap must be at least Rs 10')
        self.lock = threading.RLock()
        if cache_ttl<0:
            raise ValueError('Cache TTL cannot be negative')
        self.cache_ttl=cache_ttl;self.clock=clock;self.flight_cache={}

    def flight_rows(self,airport):
        with self.lock:
            current=self.clock()
            cached=self.flight_cache.get(airport)
            if cached and current-cached[0]<self.cache_ttl:
                return [dict(r) for r in cached[1]],'HIT'
            with self.transaction() as db:
                rows=[dict(r) for r in db.execute('SELECT * FROM flights WHERE airport=? ORDER BY scheduled,id',(airport,))]
            if self.cache_ttl:
                self.flight_cache[airport]=(current,rows)
            return [dict(r) for r in rows],'MISS'

    def health(self,poll_seconds):
        with self.transaction() as db:
            rows={r['airport']:dict(r) for r in db.execute('SELECT * FROM ingest_health')}
            result=[]
            for hub in self.demo['airports']:
                row=rows.get(hub['code'],{})
                success=row.get('last_success_at')
                age=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(success)).total_seconds()) if success else None
                status=('never_ingested' if success is None else 'stale' if age>max(1,poll_seconds*2)
                        else 'degraded' if not row.get('last_attempt_ok') else 'ok')
                result.append(dict(airport=hub['code'],status=status,last_success_at=success,source=row.get('source'),
                    age_seconds=round(age,2) if age is not None else None,last_attempt_at=row.get('last_attempt_at'),
                    last_attempt_ok=bool(row['last_attempt_ok']) if 'last_attempt_ok' in row else None,
                    flight_count=row.get('flight_count'),last_error=row.get('last_error'),
                    synthetic=row.get('source')=='demo'))
            return dict(status='ok' if all(r['status']=='ok' for r in result) else 'degraded',
                        database='ok',poll_seconds=poll_seconds,airports=result)

    def connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        return connection

    @contextmanager
    def transaction(self):
        with self.lock:
            db = self.connect()
            try:
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def initialize(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            db = self.connect()
            try:
                init_db(db)
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS pool_groups (
                        id TEXT PRIMARY KEY, airport TEXT NOT NULL, terminal TEXT,
                        state TEXT NOT NULL DEFAULT 'queued', driver_id TEXT
                    );
                    CREATE TABLE IF NOT EXISTS bookings (
                        id TEXT PRIMARY KEY, flight_id TEXT NOT NULL REFERENCES flights(id),
                        destination TEXT NOT NULL, airport TEXT NOT NULL, terminal TEXT,
                        ready_time TEXT NOT NULL, gender TEXT NOT NULL, party INTEGER NOT NULL,
                        bags INTEGER NOT NULL, max_wait INTEGER NOT NULL, women_only INTEGER NOT NULL,
                        solo_fare REAL NOT NULL, group_id TEXT REFERENCES pool_groups(id),
                        status TEXT NOT NULL DEFAULT 'quoted', quote_version INTEGER NOT NULL DEFAULT 1,
                        per_seat REAL NOT NULL DEFAULT 0, amount REAL NOT NULL DEFAULT 0,
                        locked_per_seat REAL, locked_amount REAL, locked_solo_fare REAL, pickup_code TEXT,
                        created_at TEXT NOT NULL,ride_type TEXT NOT NULL DEFAULT 'pool'
                    );
                    CREATE TABLE IF NOT EXISTS notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id TEXT NOT NULL REFERENCES bookings(id),
                        flight_id TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS api_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    INSERT OR IGNORE INTO api_meta VALUES ('change_cursor','0');
                    CREATE TABLE IF NOT EXISTS wallets (id TEXT PRIMARY KEY,balance_paise INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS wallet_ledger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,wallet_id TEXT NOT NULL REFERENCES wallets(id),
                        booking_id TEXT,amount_paise INTEGER NOT NULL,label TEXT NOT NULL,created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS payments (
                        booking_id TEXT PRIMARY KEY REFERENCES bookings(id),wallet_id TEXT NOT NULL REFERENCES wallets(id),
                        wallet_paise INTEGER NOT NULL,method_paise INTEGER NOT NULL,method TEXT NOT NULL,
                        refunded INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS support_tickets (
                        id TEXT PRIMARY KEY,wallet_id TEXT NOT NULL,booking_id TEXT,message TEXT NOT NULL,created_at TEXT NOT NULL
                    );
                ''')
                # Bootstrap empty airports, without overwriting existing live ETAs.
                from flight_ingest import upsert_flights
                if 'locked_solo_fare' not in {r[1] for r in db.execute('PRAGMA table_info(bookings)')}:
                    db.execute('ALTER TABLE bookings ADD COLUMN locked_solo_fare REAL')
                    db.execute('UPDATE bookings SET locked_solo_fare=solo_fare WHERE locked_amount IS NOT NULL')
                    db.commit()
                if 'ride_type' not in {r[1] for r in db.execute('PRAGMA table_info(bookings)')}:
                    db.execute("ALTER TABLE bookings ADD COLUMN ride_type TEXT NOT NULL DEFAULT 'pool'")
                    db.commit()
                # Use supplied demo file data rather than a fixed bootstrap path.
                from flight_ingest import normalise_flight
                missing = [normalise_flight(r,r['airport'],'demo') for r in self.demo['flights']
                           if not db.execute('SELECT 1 FROM flights WHERE id=?',(r['id'],)).fetchone()]
                upsert_flights(db, missing)
            finally:
                db.close()

    def airport(self, airport):
        if airport not in {h['code'] for h in self.demo['airports']}:
            raise HTTPException(422, 'Unsupported airport')

    def as_rider(self, row):
        area = self.areas[row['destination']]
        return Rider(id=row['id'], ready_time=datetime.fromisoformat(row['ready_time']),
                     max_wait_min=row['max_wait'], lat=area['lat'], lng=area['lng'],
                     gender=row['gender'], party_size=row['party'], large_bags=row['bags'],
                     women_only=bool(row['women_only']), solo_fare=Decimal(str(row['solo_fare'])),
                     flight_id=row['flight_id'])

    def solo(self, area, ready):
        local = ready.astimezone(timezone(timedelta(hours=5,minutes=30)))
        return Decimal(str(area['day_fare'])) * (Decimal('1.2') if local.hour>=22 or local.hour<6 else Decimal('1'))

    def rows(self, db, group_id):
        return db.execute("SELECT * FROM bookings WHERE group_id=? AND status!='cancelled' ORDER BY ready_time,id",(group_id,)).fetchall()

    def ensure_wallet(self,db,identity):
        if not db.execute('SELECT 1 FROM wallets WHERE id=?',(identity,)).fetchone():
            db.execute('INSERT INTO wallets VALUES (?,15000)',(identity,))
            db.execute('INSERT INTO wallet_ledger(wallet_id,amount_paise,label,created_at) VALUES (?,15000,?,?)',
                       (identity,'Demo welcome credit',now()))

    def wallet(self,identity):
        with self.transaction() as db:
            self.ensure_wallet(db,identity)
            return dict(wallet_id=identity,balance=db.execute('SELECT balance_paise FROM wallets WHERE id=?',(identity,)).fetchone()[0]/100,
                        transactions=[dict(id=r['id'],amount=r['amount_paise']/100,label=r['label'],created_at=r['created_at'])
                                      for r in db.execute('SELECT * FROM wallet_ledger WHERE wallet_id=? ORDER BY id DESC',(identity,))],demo=True)

    def reprice(self, db, group_id):
        rows = self.rows(db, group_id)
        if not rows:
            return
        quote = quote_fare(tuple(self.as_rider(r) for r in rows))
        for row in rows:
            # Guarantee no party pays more than its solo cab quote or cap.
            # Floor the ceiling to Rs 10 per seat so the cap survives rounding.
            ceiling = min(Decimal(str(row['solo_fare'])), self.solo_cap)/row['party']
            ceiling = (ceiling/10).quantize(Decimal('1'),rounding=ROUND_FLOOR)*10
            per_seat = min(quote.fare_per_seat,ceiling)
            amount = per_seat*row['party']
            changed = float(per_seat)!=row['per_seat'] or float(amount)!=row['amount']
            db.execute('UPDATE bookings SET per_seat=?,amount=?,quote_version=quote_version+? WHERE id=?',
                       (float(per_seat),float(amount),int(changed),row['id']))

    def assign_groups(self, db, groups, old_ids):
        """Replace only selected queued groups; locked booking amounts survive."""
        affected = [r.id for g in groups for r in g]
        for identity in affected:
            db.execute('UPDATE bookings SET group_id=NULL WHERE id=?',(identity,))
        for identity in old_ids:
            db.execute('DELETE FROM pool_groups WHERE id=?',(identity,))
        for group in groups:
            first = db.execute('SELECT airport,terminal FROM bookings WHERE id=?',(group[0].id,)).fetchone()
            group_id = uid()
            db.execute('INSERT INTO pool_groups(id,airport,terminal) VALUES (?,?,?)',
                       (group_id,first['airport'],first['terminal']))
            for r in group:
                db.execute('UPDATE bookings SET group_id=?,ready_time=? WHERE id=?',
                           (group_id,r.ready_time.isoformat(),r.id))
            self.reprice(db,group_id)
            if db.execute("SELECT 1 FROM bookings WHERE group_id=? AND status='booked'",(group_id,)).fetchone():
                self.assign_driver(db,group_id)

    def assign_driver(self, db, group_id):
        group = db.execute('SELECT * FROM pool_groups WHERE id=?',(group_id,)).fetchone()
        busy = {r[0] for r in db.execute("SELECT driver_id FROM pool_groups WHERE state!='completed' AND driver_id IS NOT NULL")}
        driver = next((d['id'] for d in self.demo['drivers'] if d['airport']==group['airport'] and d['id'] not in busy),None)
        # No-driver is visible as awaiting_driver; the price/booking still exists.
        db.execute('UPDATE pool_groups SET driver_id=? WHERE id=?',(driver,group_id))

    def result(self, db, identity):
        row = db.execute('SELECT * FROM bookings WHERE id=?',(identity,)).fetchone()
        if not row:
            raise HTTPException(404, 'Unknown match/booking')
        if row['status']=='cancelled':
            return dict(match_id=row['id'],booking_id=row['id'],status='cancelled',price_locked=True)
        members = self.rows(db,row['group_id'])
        amount = row['locked_amount'] if row['locked_amount'] is not None else row['amount']
        per_seat = row['locked_per_seat'] if row['locked_per_seat'] is not None else row['per_seat']
        baseline = row['locked_solo_fare'] if row['locked_solo_fare'] is not None else row['solo_fare']
        saving = round(baseline-amount,2)
        group = db.execute('SELECT * FROM pool_groups WHERE id=?',(row['group_id'],)).fetchone()
        payment=db.execute('SELECT * FROM payments WHERE booking_id=?',(identity,)).fetchone()
        return dict(match_id=row['id'],booking_id=row['id'] if row['status']!='quoted' else None,
                    quote_version=row['quote_version'],status=row['status'],trip_id=row['group_id'],
                    option='pool' if len(members)>1 else 'solo',ride_type=row['ride_type'],price_locked=row['locked_amount'] is not None,
                    per_seat_fare=per_seat,total_fare=amount,solo_fare=baseline,current_solo_fare=row['solo_fare'],savings=saving,
                    savings_percent=round(100*saving/baseline,2) if baseline else 0,
                    solo_price_cap=float(self.solo_cap),pickup_code=row['pickup_code'],
                    payment=dict(wallet_applied=payment['wallet_paise']/100,payment_amount=payment['method_paise']/100,
                                 method=payment['method'],demo=True) if payment else None,
                    driver_status='assigned' if group['driver_id'] else 'awaiting_driver',
                    trip_state=group['state'],
                    group=[dict(id=m['id'],destination=m['destination'],ready_time=m['ready_time'],
                                party=m['party'],bags=m['bags'],status=m['status']) for m in members])

    def match(self, request):
        if request.women_only and request.gender not in (None,'woman'):
            raise HTTPException(422,'women_only requires an all-women party')
        gender = request.gender or ('woman' if request.women_only else 'unknown')
        with self.transaction() as db:
            flight = db.execute('SELECT * FROM flights WHERE id=?',(request.flight_id,)).fetchone()
            if not flight:
                raise HTTPException(404,'Unknown flight')
            if flight['status'].lower() in ('cancelled','canceled'):
                raise HTTPException(409,'Flight is cancelled')
            area = self.areas.get(request.destination) or next((a for a in self.areas.values()
                if a['airport']==flight['airport'] and a['name']==request.destination),None)
            if not area or area['airport']!=flight['airport']:
                raise HTTPException(422,'Destination must belong to the arrival airport')
            ready = datetime.fromisoformat(flight['estimated'])+timedelta(minutes=22 if request.bags else 12)
            # Time-prefixed IDs preserve arrival order at identical ready times,
            # because the pure matcher resolves ties by ID.
            identity = f'{time.time_ns():020}-{uid()}'
            db.execute('''INSERT INTO bookings(id,flight_id,destination,airport,terminal,ready_time,gender,
                party,bags,max_wait,women_only,solo_fare,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (identity,request.flight_id,area['id'],flight['airport'],flight['terminal'],ready.isoformat(),
                 gender,request.party,request.bags,request.max_wait,int(request.women_only),float(self.solo(area,ready)),now()))
            db.execute('UPDATE bookings SET ride_type=? WHERE id=?',(request.ride_type,identity))
            if request.ride_type=='private':
                row=db.execute('SELECT * FROM bookings WHERE id=?',(identity,)).fetchone()
                self.assign_groups(db,((self.as_rider(row),),),())
                return self.result(db,identity)
            # Keep pickup airport AND terminal partitions separate. Do not move
            # already-dispatched/completed riders into new matches.
            rows = db.execute('''SELECT b.* FROM bookings b LEFT JOIN pool_groups g ON g.id=b.group_id
                WHERE b.airport=? AND b.terminal IS ? AND b.ride_type='pool' AND b.status IN ('quoted','booked') AND (g.state='queued' OR b.group_id IS NULL)''',
                (flight['airport'],flight['terminal'])).fetchall()
            old = {r['group_id'] for r in rows if r['group_id']}
            self.assign_groups(db,match_riders(self.as_rider(r) for r in rows),old)
            return self.result(db,identity)

    def book(self, request):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM bookings WHERE id=?',(request.match_id,)).fetchone()
            if not row:
                raise HTTPException(404,'Unknown match')
            if row['status']!='quoted':
                payment=db.execute('SELECT wallet_id FROM payments WHERE booking_id=?',(row['id'],)).fetchone()
                if payment and payment[0]!=request.wallet_id:
                    raise HTTPException(403,'Booking belongs to a different wallet')
                return self.result(db,row['id'])  # Idempotent retry; same price/code.
            if request.quote_version!=row['quote_version']:
                raise HTTPException(409,'Quote changed; refresh GET /match/{match_id}')
            group = db.execute('SELECT * FROM pool_groups WHERE id=?',(row['group_id'],)).fetchone()
            if group['state']!='queued':
                raise HTTPException(409,'Trip has dispatched; request a new match')
            used = {r[0] for r in db.execute("SELECT pickup_code FROM bookings WHERE status='booked'")}
            available = [f'{i:04}' for i in range(1000,10000) if f'{i:04}' not in used]
            if not available:
                raise HTTPException(503,'Pickup codes temporarily exhausted')
            code = secrets.choice(available)
            self.ensure_wallet(db,request.wallet_id)
            balance=db.execute('SELECT balance_paise FROM wallets WHERE id=?',(request.wallet_id,)).fetchone()[0]
            amount=int(round(row['amount']*100))
            applied=min(balance,amount)
            db.execute('UPDATE wallets SET balance_paise=balance_paise-? WHERE id=?',(applied,request.wallet_id))
            db.execute('INSERT INTO wallet_ledger(wallet_id,booking_id,amount_paise,label,created_at) VALUES (?,?,?,?,?)',
                       (request.wallet_id,row['id'],-applied,'Wallet applied before payment',now()))
            db.execute('INSERT INTO payments(booking_id,wallet_id,wallet_paise,method_paise,method) VALUES (?,?,?,?,?)',
                       (row['id'],request.wallet_id,applied,amount-applied,request.payment_method))
            db.execute("UPDATE bookings SET status='booked',locked_per_seat=per_seat,locked_amount=amount,locked_solo_fare=solo_fare,pickup_code=? WHERE id=?",(code,row['id']))
            if not group['driver_id']:
                self.assign_driver(db,group['id'])
            return self.result(db,row['id'])

    def cancel(self,request):
        with self.transaction() as db:
            row=db.execute('SELECT * FROM bookings WHERE id=?',(request.booking_id,)).fetchone()
            payment=db.execute('SELECT * FROM payments WHERE booking_id=?',(request.booking_id,)).fetchone()
            if not row or not payment:
                raise HTTPException(404,'Unknown paid booking')
            if payment['wallet_id']!=request.wallet_id:
                raise HTTPException(403,'Booking belongs to a different wallet')
            refund=payment['wallet_paise']+(payment['method_paise'] if payment['method']!='cash' else 0)
            if payment['refunded']:
                return dict(status='cancelled',wallet_refund=refund/100,already_refunded=True)
            group=db.execute('SELECT * FROM pool_groups WHERE id=?',(row['group_id'],)).fetchone()
            if not group or group['state'] not in ('queued','en_route','arrived'):
                raise HTTPException(409,'Cannot cancel after pickup')
            db.execute('UPDATE wallets SET balance_paise=balance_paise+? WHERE id=?',(refund,request.wallet_id))
            db.execute('INSERT INTO wallet_ledger(wallet_id,booking_id,amount_paise,label,created_at) VALUES (?,?,?,?,?)',
                       (request.wallet_id,row['id'],refund,'Refund: '+request.reason.replace('_',' '),now()))
            db.execute('UPDATE payments SET refunded=1 WHERE booking_id=?',(row['id'],))
            db.execute("UPDATE bookings SET status='cancelled',group_id=NULL WHERE id=?",(row['id'],))
            if not self.rows(db,group['id']):
                db.execute('DELETE FROM pool_groups WHERE id=?',(group['id'],))
            elif group['state']=='queued':
                self.reprice(db,group['id'])
            return dict(status='cancelled',wallet_refund=refund/100,already_refunded=False)

    def process_changes(self):
        """Durable cursor: ETA notifications survive a restart between polls."""
        with self.transaction() as db:
            cursor = int(db.execute("SELECT value FROM api_meta WHERE key='change_cursor'").fetchone()[0])
            events = db.execute('SELECT * FROM changes WHERE change_id>? ORDER BY change_id',(cursor,)).fetchall()
            flights = dict.fromkeys(e['flight_id'] for e in events)
            for flight_id in flights:
                flight = db.execute('SELECT * FROM flights WHERE id=?',(flight_id,)).fetchone()
                affected_groups = db.execute('''SELECT DISTINCT g.* FROM pool_groups g JOIN bookings b ON b.group_id=g.id
                    WHERE b.flight_id=? AND g.state!='completed' ''',(flight_id,)).fetchall()
                queued = [g for g in affected_groups if g['state']=='queued']
                old_ids = [g['id'] for g in queued]
                pool_groups=[];private_groups=[]
                for g in queued:
                    rows=self.rows(db,g['id'])
                    members=tuple(self.as_rider(r) for r in rows)
                    (private_groups if rows[0]['ride_type']=='private' else pool_groups).append(members)
                eta=datetime.fromisoformat(flight['estimated'])
                updated = rematch_flight(tuple(pool_groups),flight_id,eta)
                for members in private_groups:
                    private=rematch_flight((members,),flight_id,eta)
                    updated=replace(updated,groups=updated.groups+private.groups,
                        affected_rider_ids=updated.affected_rider_ids+private.affected_rider_ids,
                        changed_flight_rider_ids=updated.changed_flight_rider_ids+private.changed_flight_rider_ids)
                for g in updated.groups:
                    for r in g:
                        if r.flight_id==flight_id:
                            solo = self.solo(self.areas[db.execute('SELECT destination FROM bookings WHERE id=?',(r.id,)).fetchone()[0]],r.ready_time)
                            db.execute('UPDATE bookings SET solo_fare=? WHERE id=?',(float(solo),r.id))
                if old_ids:
                    # Refresh Rider fare inputs before reprice; rematch used times only.
                    refreshed = tuple(tuple(replace(r,solo_fare=Decimal(str(db.execute('SELECT solo_fare FROM bookings WHERE id=?',(r.id,)).fetchone()[0]))) for r in g) for g in updated.groups)
                    self.assign_groups(db,refreshed,old_ids)
                notified = set(updated.affected_rider_ids)
                for g in affected_groups:
                    if g['state']!='queued':
                        notified.update(r['id'] for r in self.rows(db,g['id']))
                for identity in notified:
                    db.execute('INSERT INTO notifications(booking_id,flight_id,message,created_at) VALUES (?,?,?,?)',
                        (identity,flight_id,'Flight ETA changed. Queued groups were re-matched; locked prices are preserved. Dispatched trips require driver coordination.',now()))
            if events:
                db.execute("UPDATE api_meta SET value=? WHERE key='change_cursor'",(str(events[-1]['change_id']),))
            return list(flights)

    def ingest_tick(self):
        with self.lock:
            db = self.connect()
            try:
                changed = poll_once(db,self.providers)
            finally:
                db.close()
                # Invalidate on every poll, including status-only updates and
                # any successful airports before a later airport failed.
                self.flight_cache.clear()
            self.process_changes()
            return changed

    def driver_trip(self, db, group):
        members = [r for r in self.rows(db,group['id']) if r['status']!='quoted']
        return dict(trip_id=group['id'],airport=group['airport'],terminal=group['terminal'],
                    driver_id=group['driver_id'],state=group['state'],
                    riders=[dict(booking_id=r['id'],destination=r['destination'],party=r['party'],bags=r['bags'],
                                 ready_time=r['ready_time'],locked_fare=r['locked_amount']) for r in members],
                    occupied_seats=sum(r['party'] for r in members),large_bags=sum(r['bags'] for r in members))

    def step(self, request):
        sequence = dict(queued='en_route',en_route='arrived',arrived='picked_up',picked_up='completed')
        with self.transaction() as db:
            group = db.execute('SELECT * FROM pool_groups WHERE id=?',(request.trip_id,)).fetchone()
            if not group:
                raise HTTPException(404,'Unknown trip')
            if not group['driver_id']:
                self.assign_driver(db,group['id'])
                group = db.execute('SELECT * FROM pool_groups WHERE id=?',(group['id'],)).fetchone()
            if not group['driver_id']:
                raise HTTPException(409,'Trip is awaiting a driver')
            if group['state']==request.step:
                return self.driver_trip(db,group)
            if sequence.get(group['state'])!=request.step:
                raise HTTPException(409,'Invalid driver state transition')
            rows = self.rows(db,group['id'])
            confirmed = [r for r in rows if r['status']=='booked']
            if not confirmed:
                raise HTTPException(409,'Trip has no confirmed bookings')
            if request.step=='en_route':
                # Remove provisional companions at dispatch and give each an
                # independent fresh quote; confirmed price locks remain intact.
                for row in rows:
                    if row['status']=='quoted':
                        new_id = uid()
                        db.execute('INSERT INTO pool_groups(id,airport,terminal) VALUES (?,?,?)',(new_id,row['airport'],row['terminal']))
                        db.execute('UPDATE bookings SET group_id=? WHERE id=?',(new_id,row['id']))
                        self.reprice(db,new_id)
            if request.step=='picked_up':
                codes = request.pickup_codes or {}
                if any(codes.get(r['id'])!=r['pickup_code'] for r in confirmed):
                    raise HTTPException(422,'Correct pickup code required for each confirmed booking')
            db.execute('UPDATE pool_groups SET state=? WHERE id=?',(request.step,group['id']))
            if request.step=='completed':
                db.execute("UPDATE bookings SET status='completed' WHERE group_id=?",(group['id'],))
            return self.driver_trip(db,db.execute('SELECT * FROM pool_groups WHERE id=?',(group['id'],)).fetchone())

    def summary(self):
        def metrics(trips):
            cabs = len(trips)
            bookings = sum(t['bookings'] for t in trips)
            people = sum(t['seats'] for t in trips)
            return dict(cabs_needed=cabs,fewer_cars_percent=round(100*(1-cabs/bookings),2) if bookings else 0,
                        rider_savings=round(sum(t['savings'] for t in trips),2),
                        average_riders_per_cab=round(people/cabs,2) if cabs else 0,
                        passenger_bookings=bookings,occupied_seats=people)
        with self.transaction() as db:
            trips = []
            for group in db.execute('SELECT * FROM pool_groups'):
                rows = [r for r in self.rows(db,group['id']) if r['status']!='quoted']
                if rows:
                    trips.append(dict(bookings=len(rows),seats=sum(r['party'] for r in rows),
                                      savings=sum(r['locked_solo_fare']-r['locked_amount'] for r in rows)))
            result = metrics(trips)
            result['active_cabs_needed'] = db.execute("SELECT COUNT(*) FROM pool_groups g WHERE g.state!='completed' AND EXISTS (SELECT 1 FROM bookings b WHERE b.group_id=g.id AND b.status='booked')").fetchone()[0]
            result['awaiting_driver'] = db.execute("SELECT COUNT(*) FROM pool_groups g WHERE g.state!='completed' AND g.driver_id IS NULL AND EXISTS (SELECT 1 FROM bookings b WHERE b.group_id=g.id AND b.status='booked')").fetchone()[0]
            result['history_14_days'] = [dict(date=day['date'],**metrics([dict(bookings=t['pool_size'],seats=t['occupied_seats'],
                savings=sum(a['solo_fare']-a['fare'] for a in t['allocations'])) for t in day['trips']])) for day in self.demo['trip_history']]
            result['history_source'] = 'synthetic demo, original generator pricing'
            result['baseline'] = 'one separate cab per passenger booking (a party counts as one cab)'
            return result


def create_app(db_path=None,demo_path=None,offline=True,background=True,poll_seconds=300,providers=None,solo_cap=2500,
               flights_cache_ttl=10,flights_rate_limit=60,flights_rate_window=60,clock=time.monotonic):
    if poll_seconds<=0:
        raise ValueError('Poll interval must be positive')
    demo_path = Path(demo_path or HERE/'airpool_demo_data.json')
    providers = providers if providers is not None else ([DemoProvider(demo_path)] if offline else
        [AeroDataBoxProvider(),AirportScraper(),DemoProvider(demo_path)])
    store = Store(db_path or HERE/'airpool_flights.sqlite3',demo_path,providers,solo_cap,flights_cache_ttl,clock)
    limiter=FlightsLimiter(flights_rate_limit,flights_rate_window,clock)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.initialize)
        await asyncio.to_thread(store.process_changes)
        stop = asyncio.Event()
        async def ingest_loop():
            while not stop.is_set():
                started = asyncio.get_running_loop().time()
                try:
                    await asyncio.to_thread(store.ingest_tick)
                except Exception:
                    LOG.exception('Ingestion tick failed; retrying next poll')
                delay = max(0,poll_seconds-(asyncio.get_running_loop().time()-started))
                try:
                    await asyncio.wait_for(stop.wait(),timeout=delay)
                except asyncio.TimeoutError:
                    pass
        task = asyncio.create_task(ingest_loop()) if background else None
        try:
            yield
        finally:
            stop.set()
            if task:
                await task

    app = FastAPI(title='Hoppr airport pooling demo',lifespan=lifespan)
    app.state.store = store

    @app.get('/flights')
    def flights(request: Request,response: Response,airport: str='DEL'):
        store.airport(airport)
        headers=limiter.check(request.client.host if request.client else 'unknown')
        rows,cache_status=store.flight_rows(airport)
        response.headers.update({**headers,'X-Cache':cache_status,'Cache-Control':'no-store'})
        return rows

    @app.get('/health')
    def health():
        return store.health(poll_seconds)

    @app.get('/destinations')
    def destinations(airport: str='DEL'):
        store.airport(airport)
        return [a for a in store.areas.values() if a['airport']==airport]

    @app.post('/match')
    def match(request: MatchRequest):
        return store.match(request)

    @app.get('/match/{match_id}')
    def current_match(match_id: str):
        with store.transaction() as db:
            return store.result(db,match_id)

    @app.post('/book')
    def book(request: BookRequest):
        return store.book(request)

    @app.get('/wallet')
    def wallet(wallet_id: str='demo'):
        if not 1<=len(wallet_id)<=80:
            raise HTTPException(422,'Invalid wallet ID')
        return store.wallet(wallet_id)

    @app.post('/cancel')
    def cancel(request: CancelRequest):
        return store.cancel(request)

    @app.post('/support')
    def support(request: SupportRequest):
        identity=uid()
        with store.transaction() as db:
            if request.booking_id and not db.execute('SELECT 1 FROM bookings WHERE id=?',(request.booking_id,)).fetchone():
                raise HTTPException(404,'Unknown booking')
            db.execute('INSERT INTO support_tickets VALUES (?,?,?,?,?)',
                       (identity,request.wallet_id,request.booking_id,request.message,now()))
        return dict(ticket_id=identity,status='saved',demo=True)

    @app.get('/driver/trip')
    def driver_trip(trip_id: str | None=None,driver_id: str | None=None):
        with store.transaction() as db:
            groups = db.execute("SELECT * FROM pool_groups WHERE state!='completed' ORDER BY id").fetchall()
            return [store.driver_trip(db,g) for g in groups if (trip_id is None or g['id']==trip_id)
                    and (driver_id is None or g['driver_id']==driver_id)
                    and db.execute("SELECT 1 FROM bookings WHERE group_id=? AND status='booked'",(g['id'],)).fetchone()]

    @app.post('/driver/step')
    def driver_step(request: StepRequest):
        return store.step(request)

    @app.get('/notifications')
    def notifications(booking_id: str):
        with store.transaction() as db:
            if not db.execute('SELECT 1 FROM bookings WHERE id=?',(booking_id,)).fetchone():
                raise HTTPException(404,'Unknown booking')
            return [dict(r) for r in db.execute('SELECT * FROM notifications WHERE booking_id=? ORDER BY id',(booking_id,))]

    @app.get('/ops/summary')
    def summary():
        return store.summary()

    frontend=HERE/'static'
    if frontend.is_dir():
        app.mount('/static',StaticFiles(directory=frontend),name='static')
        @app.get('/',include_in_schema=False)
        def home():
            return FileResponse(frontend/'index.html')

    return app


app = create_app(db_path=os.environ.get('AIRPOOL_DB'),offline=os.environ.get('AIRPOOL_OFFLINE','1')!='0',
                 demo_path=os.environ.get('AIRPOOL_DEMO'),
                 poll_seconds=float(os.environ.get('AIRPOOL_POLL_SECONDS','300')),
                 solo_cap=float(os.environ.get('AIRPOOL_SOLO_CAP','2500')),
                 flights_cache_ttl=float(os.environ.get('AIRPOOL_FLIGHTS_CACHE_TTL','10')),
                 flights_rate_limit=int(os.environ.get('AIRPOOL_FLIGHTS_RATE_LIMIT','60')),
                 flights_rate_window=float(os.environ.get('AIRPOOL_FLIGHTS_RATE_WINDOW','60')))
