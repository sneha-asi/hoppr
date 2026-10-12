"""Arrival ingestion scaffold. Live calls have NOT been validated.

Run offline: python flight_ingest.py --offline --once
Without --once, poll every 300 seconds. Requires only the Python stdlib.
API docs: https://doc.aerodatabox.com/rapidapi.html
"""
import argparse
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOG = logging.getLogger(__name__)
AIRPORTS = ('DEL','BOM','BLR')
FIELDS = ('id','airport','flight_no','airline','origin','terminal','scheduled',
          'estimated','delay_min','status','source')
POLL_SECONDS = 300


class ProviderError(Exception):
    def __init__(self,message,code='provider_error',http_status=None):
        super().__init__(message)
        self.code=code
        self.http_status=http_status


def log_event(level,event,**fields):
    """JSON log records; never include raw exception text, bodies or secrets."""
    record=dict(timestamp=datetime.now(timezone.utc).isoformat(),event=event,**fields)
    LOG.log(level,json.dumps(record,sort_keys=True),extra={'event':event,'context':fields})


def timestamp(value):
    """Canonical UTC ISO timestamp; reject ambiguous times without an offset."""
    parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include a UTC offset')
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')


def api_time(value):
    # TODO(verify): time values are DateTime objects containing utc or local,
    # or ISO strings; local includes its UTC offset. Reject offset-free values.
    if isinstance(value,dict):
        value = value.get('utc') or value.get('local')
    if not isinstance(value,str) or not value:
        raise ValueError('Missing flight timestamp')
    return timestamp(value)


def normalise_flight(row, airport, source='aerodatabox'):
    """Normalise one arrival. All API field assumptions remain unverified."""
    if not isinstance(row,dict):
        raise ValueError('Flight row must be an object')
    if source == 'demo':
        scheduled = timestamp(row['scheduled_landing'])
        estimated = timestamp(row['estimated_landing'])
        number = row['flight_number'].replace(' ','').upper()
        airline = row['airline_code']
        origin = row.get('origin')  # Demo dataset has no origin; do not invent one.
        terminal = row.get('terminal')
        status = row.get('status') or ('delayed' if estimated>scheduled else 'scheduled')
        identity = row['id']  # Preserve demo passenger flight_id references.
    else:
        # TODO(verify): withLeg=true returns arrival/departure objects. movement
        # is accepted for the alternate withLeg=false representation.
        movement = row.get('arrival') or row.get('movement')
        if not isinstance(movement,dict):
            raise ValueError('Missing arrival movement')
        # TODO(verify): number identifies the marketed flight, including airline
        # prefix. scheduledTime is mandatory; revisedTime is the ETA update.
        number = str(row.get('number') or '').replace(' ','').upper()
        if not number:
            raise ValueError('Missing flight number')
        scheduled = api_time(movement.get('scheduledTime'))
        # TODO(verify): missing revisedTime means scheduled time; actual landing
        # is not substituted for ETA. Confirm provider semantics before live use.
        revised = movement.get('revisedTime')
        estimated = api_time(revised) if revised else scheduled
        # TODO(verify): airline has iata/name; prefer IATA. Both may be absent.
        carrier = row.get('airline') or {}
        if not isinstance(carrier,dict):
            raise ValueError('Airline must be an object')
        airline = carrier.get('iata') or carrier.get('name')
        # TODO(verify): departure.airport gives origin for withLeg=true; the
        # movement.airport represents the opposite airport for withLeg=false.
        departure = row.get('departure') or {}
        if not isinstance(departure,dict):
            raise ValueError('Departure must be an object')
        origin_airport = departure.get('airport') or movement.get('airport') or {}
        if not isinstance(origin_airport,dict):
            raise ValueError('Origin airport must be an object')
        origin = origin_airport.get('iata') or origin_airport.get('icao') or origin_airport.get('name')
        # TODO(verify): terminal is under arrival/movement and status is a
        # top-level string. Preserve provider vocabulary in lowercase.
        terminal = movement.get('terminal')
        status = str(row.get('status') or 'unknown').lower()
        # TODO(verify): airport+flight number+scheduled arrival LOCAL date is
        # stable across ETA changes. Codeshares and duplicate daily legs may
        # need a provider-specific immutable ID once real responses are checked.
        raw_scheduled = movement['scheduledTime']
        if isinstance(raw_scheduled,dict):
            raw_local = raw_scheduled.get('local') or raw_scheduled.get('utc')
        else:
            raw_local = raw_scheduled
        local_date = datetime.fromisoformat(raw_local.replace('Z','+00:00')).date().isoformat()
        identity = f'{airport}:{number}:{local_date}'
    delay = (datetime.fromisoformat(estimated)-datetime.fromisoformat(scheduled)).total_seconds()/60
    return dict(id=identity,airport=airport,flight_no=number,airline=airline,origin=origin,
                terminal=str(terminal) if terminal is not None else None,scheduled=scheduled,
                estimated=estimated,delay_min=round(delay,2),status=status,source=source)


class AeroDataBoxProvider:
    name = 'aerodatabox'

    def __init__(self,key=None,timeout=20):
        self.key = key if key is not None else os.environ.get('AERODATABOX_KEY')
        self.timeout = timeout

    def fetch(self,airport):
        if not self.key:
            raise ProviderError('AERODATABOX_KEY is not configured',code='missing_key')
        query = urlencode(dict(offsetMinutes=-30,durationMinutes=240,direction='Arrival',withLeg='true'))
        request = Request(f'https://aerodatabox.p.rapidapi.com/flights/airports/iata/{airport}?{query}',
            headers={'X-RapidAPI-Key':self.key,'X-RapidAPI-Host':'aerodatabox.p.rapidapi.com',
                     'Accept':'application/json'})
        try:
            with urlopen(request,timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            # Never include request headers, credentials or response bodies.
            raise ProviderError(f'HTTP {error.code}',code='http_error',http_status=error.code) from None
        except (URLError,TimeoutError,OSError,json.JSONDecodeError):
            raise ProviderError('Transport failure or invalid JSON',code='transport_or_json_error') from None
        # TODO(verify): root object has an arrivals list, not pagination/wrapper.
        # A valid empty list is success: do not fabricate demo flights in that case.
        if not isinstance(payload,dict) or not isinstance(payload.get('arrivals'),list):
            raise ProviderError('Unexpected arrival response shape',code='invalid_response_shape')
        return [normalise_flight(row,airport,self.name) for row in payload['arrivals']]


class AirportScraper:
    """Skeleton only. Check each airport site's terms and robots.txt BEFORE
    implementing any scraper. No site is scraped by this scaffold.
    """
    name = 'scraper'

    def fetch(self,airport):
        raise NotImplementedError('Airport scraper is intentionally not implemented')


class DemoProvider:
    name = 'demo'

    def __init__(self,path):
        self.path = Path(path)

    def fetch(self,airport):
        with self.path.open(encoding='utf-8') as stream:
            payload = json.load(stream)
        rows = [r for r in payload['flights'] if r['airport']==airport]
        if not rows:
            raise ProviderError('Demo data has no flights for this airport')
        # Deliberately retain the fixed demo dates, not pretend these are live.
        return [normalise_flight(row,airport,self.name) for row in rows]


def fetch_first_success(airport,providers,with_source=False):
    """First successful fetch wins, independently for each airport."""
    for attempt,provider in enumerate(providers,1):
        try:
            rows = provider.fetch(airport)
            return (rows,provider.name) if with_source else rows
        except Exception as error:
            # Log only safe labels; exceptions may contain secrets from custom providers.
            code=(error.code if isinstance(error,ProviderError) else
                  'not_implemented' if isinstance(error,NotImplementedError) else
                  'invalid_data' if isinstance(error,(ValueError,KeyError,TypeError)) else
                  'io_error' if isinstance(error,OSError) else 'unexpected_error')
            log_event(logging.WARNING,'provider_failure',airport=airport,provider=provider.name,
                      attempt=attempt,error_type=type(error).__name__,error_code=code,
                      http_status=error.http_status if isinstance(error,ProviderError) else None)
    raise ProviderError(f'All providers failed for {airport}')


def init_db(connection):
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS flights (
            id TEXT PRIMARY KEY, airport TEXT NOT NULL, flight_no TEXT NOT NULL,
            airline TEXT, origin TEXT, terminal TEXT, scheduled TEXT NOT NULL,
            estimated TEXT NOT NULL, delay_min REAL NOT NULL, status TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS changes (
            change_id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id TEXT NOT NULL REFERENCES flights(id),
            old_estimated TEXT NOT NULL, new_estimated TEXT NOT NULL,
            changed_at TEXT NOT NULL, source TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS changes_flight_id ON changes(flight_id);
        CREATE TABLE IF NOT EXISTS ingest_health (
            airport TEXT PRIMARY KEY,last_success_at TEXT,source TEXT,
            last_attempt_at TEXT NOT NULL,last_attempt_ok INTEGER NOT NULL,
            flight_count INTEGER,last_error TEXT
        );
    ''')


def upsert_flights(connection,flights,changed_at=None,ingest=None):
    """Atomic batch; initial inserts aren't changes. Return unique changed IDs.

    Timestamps compare as instants via UTC normalization, not raw strings.
    """
    observed = timestamp(changed_at or datetime.now(timezone.utc).isoformat())
    changed = []
    placeholders = ','.join('?' for _ in FIELDS)
    updates = ','.join(f'{field}=excluded.{field}' for field in FIELDS if field!='id')
    with connection:
        for row in flights:
            row = dict(row)
            row['estimated'] = timestamp(row['estimated'])
            row['scheduled'] = timestamp(row['scheduled'])
            old = connection.execute('SELECT estimated FROM flights WHERE id=?',(row['id'],)).fetchone()
            connection.execute(f"INSERT INTO flights ({','.join(FIELDS)}) VALUES ({placeholders}) "
                               f'ON CONFLICT(id) DO UPDATE SET {updates}',tuple(row[f] for f in FIELDS))
            if old and timestamp(old[0])!=row['estimated']:
                connection.execute('INSERT INTO changes (flight_id,old_estimated,new_estimated,changed_at,source) '
                    'VALUES (?,?,?,?,?)',(row['id'],old[0],row['estimated'],observed,row['source']))
                if row['id'] not in changed:
                    changed.append(row['id'])
        if ingest is not None:
            airport,source,count=ingest
            connection.execute('''INSERT INTO ingest_health
                (airport,last_success_at,source,last_attempt_at,last_attempt_ok,flight_count,last_error)
                VALUES (?,?,?,?,1,?,NULL) ON CONFLICT(airport) DO UPDATE SET
                last_success_at=excluded.last_success_at,source=excluded.source,
                last_attempt_at=excluded.last_attempt_at,last_attempt_ok=1,
                flight_count=excluded.flight_count,last_error=NULL''',(airport,observed,source,observed,count))
    return changed


def poll_once(connection,providers,airports=AIRPORTS):
    changed = []
    for airport in airports:
        try:
            rows,source = fetch_first_success(airport,providers,with_source=True)
        except ProviderError:
            observed=datetime.now(timezone.utc).isoformat()
            with connection:
                connection.execute('''INSERT INTO ingest_health
                    (airport,last_attempt_at,last_attempt_ok,last_error) VALUES (?,?,0,'all_providers_failed')
                    ON CONFLICT(airport) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                    last_attempt_ok=0,last_error='all_providers_failed' ''',(airport,observed))
            log_event(logging.ERROR,'ingest_failure',airport=airport,error_code='all_providers_failed')
            continue
        ids = upsert_flights(connection,rows,ingest=(airport,source,len(rows)))
        changed.extend(i for i in ids if i not in changed)
        log_event(logging.INFO,'ingest_success',airport=airport,source=source,flight_count=len(rows),changed_count=len(ids))
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',action='store_true',help='Use only demo JSON; no network calls')
    parser.add_argument('--once',action='store_true',help='Run one poll and exit')
    parser.add_argument('--demo',type=Path,default=Path(__file__).with_name('airpool_demo_data.json'))
    parser.add_argument('--db',type=Path,default=Path(__file__).with_name('airpool_flights.sqlite3'))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    fallback = DemoProvider(args.demo)
    providers = [fallback] if args.offline else [AeroDataBoxProvider(),AirportScraper(),fallback]
    if not args.offline:
        LOG.warning('Live API calls are unvalidated; response assumptions are marked TODO(verify)')
    args.db.parent.mkdir(parents=True,exist_ok=True)
    connection = sqlite3.connect(args.db)
    try:
        init_db(connection)
        while True:
            started = time.monotonic()
            print(json.dumps({'changed_ids':poll_once(connection,providers)}),flush=True)
            if args.once:
                break
            # Start polls every five minutes, accounting for time spent fetching.
            time.sleep(max(0,POLL_SECONDS-(time.monotonic()-started)))
    except KeyboardInterrupt:
        LOG.info('Polling stopped')
    finally:
        connection.close()


if __name__=='__main__':
    main()
