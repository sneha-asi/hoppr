"""Vercel demonstration entrypoint. Local state is explicitly ephemeral."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
runtime_db = Path(tempfile.gettempdir()) / 'hoppr-vercel-demo.sqlite3'
if not runtime_db.exists():
    staging = runtime_db.with_suffix('.staging')
    shutil.copyfile(ROOT / 'platform' / 'seed.sqlite3', staging)
    staging.replace(runtime_db)
os.environ['AIRPOOL_OFFLINE'] = '1'
os.environ['HOPPR_V2_DB'] = str(runtime_db)

sys.path.insert(0, str(ROOT / 'platform'))
from backend import create_app

# Serverless requests must not own an endless provider polling loop.
app = create_app(runtime_db, background=False)

@app.get('/deployment-health')
def deployment_health():
    return {'status': 'ok', 'mode': 'hosted-demo', 'storage': 'ephemeral',
            'live_flights': False, 'real_payments': False}
