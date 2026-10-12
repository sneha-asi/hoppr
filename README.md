# Hoppr

Airport cab pooling demo: separate React Rider, Driver and Ops apps, a FastAPI
backend, pure matching functions and reproducible synthetic data.

Live demo: https://vercel-hoppr.vercel.app/rider

## Run locally

From this repository's root, using Python 3.11+ and Node 24:

```sh
python -m pip install -r outputs/requirements-api.txt
python outputs/gen_demo_data.py
python outputs/platform/gen_demo_data.py
npm --prefix outputs/platform/web ci
npm --prefix outputs/platform/web run build
python -m uvicorn backend:app --app-dir outputs/platform --port 8010
```

Open `/rider`, `/driver` or `/ops` at http://127.0.0.1:8010.
Generators refuse to overwrite a populated v2 database; use fresh output paths
for another seed. Databases and runtime sessions are intentionally not committed.

## Tests

```sh
python -m pip install -r outputs/requirements-test.txt
python -m pytest outputs/platform outputs/test_matcher.py outputs/test_api.py outputs/test_flight_ingest.py -q
```

See [platform documentation](outputs/platform/README.md) for data conventions,
environment variables, browser tests and verified versus simulated functionality.

## Prepare the Vercel demo

```sh
python prepare_hosted_demo.py
cd outputs/vercel-hoppr
vercel --prod
```

The hosted adapter uses portable public demo account selectors and temporary
SQLite storage. It is not production authentication or durable booking storage.
All people, flight snapshots, payments, GPS and verification are synthetic or
simulated. No credentials, local sessions or operational databases are included.
