import copy
import hashlib
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).parent))
import importlib.util
_spec=importlib.util.spec_from_file_location('platform_demo',Path(__file__).with_name('gen_demo_data.py'))
_module=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_module)
generate,validate=_module.generate,_module.validate
from store import connect,save_dataset

@pytest.fixture(scope='module')
def dataset():return generate(20261009)

def test_all_invariants(dataset):
    report=validate(dataset)
    assert len(report['invariants'])==9
    assert set(report['invariants'].values())=={'PASS'}
    assert 5500<len(dataset['pools'])<7500

def test_seed_reproducible(dataset):
    digest=lambda d:hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()
    assert digest(dataset)==digest(generate(20261009))

@pytest.mark.parametrize('mutation', ['orphan','capacity','money','refund','history','overlap','women','rating','cancelled'])
def test_invariants_detect_corruption(dataset,mutation):
    broken=copy.deepcopy(dataset)
    if mutation=='orphan':broken['bookings'][0]['rider_id']='missing'
    elif mutation=='capacity':broken['bookings'][0]['party']=7
    elif mutation=='money':broken['payments'][0]['net']+=1
    elif mutation=='refund':next(w for w in broken['wallet_entries'] if w['reason']=='Cancellation refund')['amount']+=1
    elif mutation=='history':broken['pools'][0]['booking_ids'].pop()
    elif mutation=='overlap':
        a=broken['pools'][0];b=next(p for p in broken['pools'][1:] if p['driver_id']==a['driver_id']);b['pickup']=a['pickup']
    elif mutation=='women':
        p=next(p for p in broken['pools'] if len(p['booking_ids'])>1);b=next(b for b in broken['bookings'] if b['id']==p['booking_ids'][0]);b['women_only']=True;b['gender']='man'
    elif mutation=='rating':broken['ratings'][0]['score']=6
    else:next(p for p in broken['payments'] if p['refund'])['driver_payout']=1
    with pytest.raises((AssertionError,KeyError,ValueError)):validate(broken)

def test_sqlite_foreign_keys_and_no_overwrite(dataset,tmp_path):
    path=tmp_path/'demo.sqlite3';save_dataset(dataset,path)
    with connect(path) as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT count(*) FROM pools').fetchone()[0]==len(dataset['pools'])
    with pytest.raises(ValueError):save_dataset(dataset,path)
