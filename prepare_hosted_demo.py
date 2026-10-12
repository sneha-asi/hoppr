"""Build source and generate a fresh synthetic database for the Vercel adapter."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
source = ROOT / 'outputs' / 'platform'
target = ROOT / 'outputs' / 'vercel-hoppr'
seed = target / 'platform' / 'seed.sqlite3'
if seed.exists():
    raise SystemExit('Hosted seed already exists; preserve it or use a fresh checkout.')
sys.path.insert(0, str(source))
spec = importlib.util.spec_from_file_location('hoppr_seed', source / 'gen_demo_data.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
data = generator.generate(20261009)
generator.validate(data)
generator.save_dataset(data, seed)
npm = shutil.which('npm.cmd' if sys.platform == 'win32' else 'npm')
if not npm:
    raise SystemExit('Install Node.js and npm first.')
for command in [['ci'], ['run', 'build']]:
    subprocess.run([npm, *command], cwd=source / 'web', check=True)
shutil.copytree(source / 'web' / 'dist', target / 'platform' / 'web' / 'dist', dirs_exist_ok=True)
index = target / 'platform' / 'web' / 'dist' / 'index.html'
notice = '<div role="status" style="padding:8px 16px;background:#fff2d6;color:#5e3d00;font:12px/1.5 sans-serif;text-align:center">Hosted demo · synthetic people and payments · bookings may reset when the server restarts. Use sample data only.</div>'
index.write_text(index.read_text(encoding='utf-8').replace('<body>', '<body>' + notice), encoding='utf-8')
print('Hosted demo prepared; deploy outputs/vercel-hoppr.')
