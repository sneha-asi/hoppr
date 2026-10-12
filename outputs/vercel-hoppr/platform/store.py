"""Shared relational demo store; cash values are integer paise."""
import json
import sqlite3
from pathlib import Path

RELATIONS = {
    'airports': {}, 'flights': {'airport_id':'airports'},
    'flight_updates': {'flight_id':'flights'}, 'riders': {},
    'drivers': {'airport_id':'airports'}, 'cabs': {'driver_id':'drivers'},
    'pools': {'airport_id':'airports','driver_id':'drivers','cab_id':'cabs'},
    'bookings': {'rider_id':'riders','flight_id':'flights','pool_id':'pools'},
    'payments': {'booking_id':'bookings'},
    'wallet_entries': {'rider_id':'riders','booking_id':'bookings'},
    'ratings': {'booking_id':'bookings'},
    'tickets': {'rider_id':'riders','booking_id':'bookings'},
    'incidents': {'pool_id':'pools'}, 'ops_users': {},
    'audit': {'ops_user_id':'ops_users'}, 'promos': {},
    'passes': {'rider_id':'riders'},
    'referrals': {'rider_id':'riders','referred_rider_id':'riders'},
    'demand_requests': {'rider_id':'riders'}, 'notifications': {},
}

def connect(path):
    db=sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    db.row_factory=sqlite3.Row
    return db

def initialize(db):
    for table,refs in RELATIONS.items():
        columns=', '.join(f'{key} TEXT REFERENCES {target}(id)' for key,target in refs.items())
        db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY, {columns+"," if columns else ""} payload TEXT NOT NULL)')
        for key in refs:
            db.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_{key} ON {table}({key})')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_payment ON payments(booking_id)')
    db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,app TEXT NOT NULL,account_id TEXT NOT NULL,role TEXT)')

def put(db,table,row):
    refs=RELATIONS[table]
    keys=['id',*refs,'payload']
    values=[row['id'],*(row.get(k) for k in refs),json.dumps(row,ensure_ascii=False)]
    db.execute(f'INSERT INTO {table}({",".join(keys)}) VALUES({",".join("?" for _ in keys)}) ON CONFLICT(id) DO UPDATE SET '+','.join(f'{k}=excluded.{k}' for k in keys[1:]),values)

def rows(db,table):
    if table not in RELATIONS: raise ValueError('Unknown entity')
    return [json.loads(r['payload']) for r in db.execute(f'SELECT payload FROM {table} ORDER BY id')]

def get(db,table,entity_id):
    if table not in RELATIONS: raise ValueError('Unknown entity')
    row=db.execute(f'SELECT payload FROM {table} WHERE id=?',(entity_id,)).fetchone()
    return json.loads(row['payload']) if row else None

def save_dataset(data,path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with connect(path) as db:
        initialize(db)
        if db.execute('SELECT count(*) FROM pools').fetchone()[0]:
            raise ValueError('Use a new database path; generation never overwrites operational records')
        for table in RELATIONS:
            for row in data[table]: put(db,table,row)
        db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('demo',json.dumps(data['metadata'])))
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
