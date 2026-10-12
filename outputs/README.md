# Hoppr airport pooling demo

The newer three-app React platform is in [platform/README.md](platform/README.md),
with Rider, Driver and Ops at port 8010. This README describes the retained
original static demo at port 8000.

A local FastAPI app with a static Rider / Driver / Ops frontend, a pure matching
module, SQLite persistence, and seeded airport demo data.

## Setup

Python 3.11 is the tested runtime. Run these commands from the directory containing
this README (`outputs/` in the supplied workspace). A virtual environment is
recommended.

```powershell
python -m pip install -r requirements-api.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

- Frontend: http://127.0.0.1:8000/
- API documentation: http://127.0.0.1:8000/docs
- Ingest health: http://127.0.0.1:8000/health

Default startup uses **offline demo ingestion**, with no live flight calls. Tables
are created automatically in `airpool_flights.sqlite3`, next to the Python files.
Use one worker: the cache/rate limiter is process-local and the background poller
needs one owner. `--no-proxy-headers` ensures the limiter uses the socket client's
IP rather than an untrusted forwarded address. Proxy deployments must configure
trusted proxies explicitly and use shared rate-limiting/cache infrastructure.

To regenerate the reproducible JSON or ingest it once without running the server:

```powershell
python gen_demo_data.py --seed 20261009
python flight_ingest.py --offline --once
```

Regeneration replaces the JSON. It does not reset existing bookings or wallet
records. Demo flights retain the fixed date 2026-10-09. The initial 210 demo riders
are not automatically enrolled as API bookings.

## Environment variables

Set variables **before** starting Uvicorn. Invalid numeric settings fail startup.
Programmatic `create_app(...)` arguments override its defaults for tests.

| Variable | Default | Meaning |
| --- | --- | --- |
| `AIRPOOL_OFFLINE` | `1` | Set exactly `0` to enable the unvalidated live provider chain; all other values use demo-only ingestion. |
| `AERODATABOX_KEY` | unset | RapidAPI key for AeroDataBox; never written to logs. Only used in online mode. |
| `AIRPOOL_DB` | `airpool_flights.sqlite3` beside `api.py` | SQLite path. |
| `AIRPOOL_DEMO` | `airpool_demo_data.json` beside `api.py` | Fallback JSON path. |
| `AIRPOOL_POLL_SECONDS` | `300` | Positive ingest poll interval in seconds. |
| `AIRPOOL_SOLO_CAP` | `2500` | INR cap per party/cab, minimum Rs 10. |
| `AIRPOOL_FLIGHTS_CACHE_TTL` | `10` | Nonnegative cache TTL in seconds; `0` disables caching. |
| `AIRPOOL_FLIGHTS_RATE_LIMIT` | `60` | Positive maximum `/flights` requests per client in the sliding window. |
| `AIRPOOL_FLIGHTS_RATE_WINDOW` | `60` | Positive window length in seconds. |

For example, in PowerShell:

```powershell
$env:AIRPOOL_OFFLINE = '1'
$env:AIRPOOL_FLIGHTS_CACHE_TTL = '10'
$env:AIRPOOL_FLIGHTS_RATE_LIMIT = '60'
```

The standalone `flight_ingest.py` uses its own `--offline`, `--demo`, `--db` and
`--once` flags; the API-specific `AIRPOOL_*` settings configure `api.py`.

## API and operational behavior

| Endpoint | Purpose |
| --- | --- |
| `GET /flights?airport=DEL` | Cached SQLite arrival rows, rate-limited per client across all airports. |
| `GET /destinations?airport=DEL` | Real area names with hand-set demo distances/fares. |
| `POST /match` | Provisional pool or capped solo quote. |
| `GET /match/{match_id}` | Current group and price lock. |
| `POST /book` | Lock the price and issue a four-digit pickup code; apply the demo wallet first. |
| `GET /driver/trip`, `POST /driver/step` | Confirmed trips and validated driver transitions. |
| `GET /ops/summary` | Booking metrics plus labeled synthetic 14-day history. |
| `GET /notifications?booking_id=...` | Stored ETA-change notifications. |
| `GET /wallet?wallet_id=...`, `POST /cancel` | Persistent demo wallet and idempotent eligible refunds. |
| `POST /support` | Save a local support ticket; no message is sent to an agent. |
| `GET /health` | Database readiness and last ingest success/source per airport. |

`/flights` returns `X-Cache: HIT` or `MISS`, plus `RateLimit-Limit`,
`RateLimit-Remaining`, and `RateLimit-Reset` (seconds until a slot becomes
available). Cached requests also count toward the limit. HTTP 429 includes
`Retry-After` in seconds. Browser caching is disabled with `Cache-Control:
no-store`; the application cache is shared by airport in this single process.
API ingest ticks invalidate it even on status-only changes. Changes made by the
standalone ingest CLI or another SQLite writer become visible within the TTL.
Quotes read SQLite directly, so fare/matching decisions do not use the board cache.
The limiter prunes inactive clients and bounds tracked client keys to 10,000.

Ingestion independently tries AeroDataBox → scraper skeleton → demo per airport;
first success wins. A valid empty list is success, not a reason to fabricate
demo flights. Each provider failure emits a JSON logging record containing
timestamp, event=`provider_failure`, airport, provider, attempt, error type, safe
error code, and HTTP status when known. Raw exceptions, payloads and credentials
are omitted. Failure of the whole chain emits `ingest_failure` and marks the last
attempt as failed without erasing the previous success. Provider runtime errors
are logged and fall through; process-control exceptions are not swallowed.

`/health` reports `last_success_at` (UTC), `source`, age, last attempt outcome,
flight count and a synthetic flag. Ingest success commits in the same transaction
as the flight rows. Records survive restarts. Bootstrapping demo rows is not
misrepresented as a successful provider poll. Airport status is `never_ingested`
until a provider poll succeeds, `degraded` after a failed attempt, or `stale` when
the last success is older than twice the poll interval; otherwise it is `ok`.
Fresh demo ingestion can be `ok` but always has `source=demo` and `synthetic=true`.
The endpoint returns HTTP 200 when it can query SQLite, with aggregate health in
the response; `ok` does **not** establish live-feed coverage. Database exceptions
produce a server error rather than an inaccurate healthy response.

## Verified

Full suite executed on 2026-10-09: **67 tests passed**, with no failures or skips.
The machine-readable results are in `test-results.xml`.

```powershell
python -m pytest . -q --junitxml=test-results.xml
```

Verified through automated tests:

- Seven scenario fixtures and additional pairwise compatibility, capacity,
  delay, party seating and fare-rounding cases.
- Seeded generation's built-in structural/reproducibility assertions; generation
  was also run successfully during initial development.
- Hand-written normalizer samples, malformed data rejection, offline ingestion,
  SQLite upserts, equivalent time offsets and atomic rollback.
- Price locks, stale-quote rejection, pickup verification, persistence, local
  re-matching and durable ETA notifications.
- Demo wallet-first payments, refund retry behavior and support ticket storage.
- Cache TTL/airport isolation, ingest invalidation, disabled cache, shared sliding
  window limits/reset, secret-free structured failure logs and persisted/stale
  health state (including empty successful responses).
- Private rides remain isolated from pools, including after ETA changes.
- FastAPI TestClient endpoint integration and static asset delivery.

Browser checks completed in the prior frontend work: three-step booking, pickup
pass, wallet application, cancellation/refund, Driver/Ops views and mobile/desktop
light/dark layout. JavaScript syntax was checked with `node --check static/app.js`.
These checks are not a complete accessibility audit or an automated browser suite.

## Unverified / demo assumptions

- **Live API field names and response semantics:** no authenticated live call has
  been verified. Field assumptions are marked `TODO(verify)` in `flight_ingest.py`.
  ETA representation, terminal/origin fields, pagination, codeshares and stable
  flight identity require validation with actual responses.
- **Real fares, routes and journey times:** coordinates/area names represent real
  places, but road kilometers, drive times, popularity, pricing coefficients,
  night surcharge and detour multiplier are hand-set demo assumptions. They do
  not establish a current commercial fare or actual route measurement.
- **Live airport coverage/delays:** fresh demo health proves only a successful
  local file read/upsert. Flight schedules and passengers are synthetic.
- **Scraping:** the scraper only raises `NotImplementedError`. Each site's terms
  and robots.txt must be checked before an implementation.
- **Payments/refunds/support:** wallet ledger entries persist, but UPI/card
  payments and refunds are simulated. No gateway or support delivery is connected.
- **Production operation:** no authenticated accounts, real driver dispatch,
  distributed rate limiter, quote expiration, fleet availability guarantee or
  payment/subsidy reconciliation has been verified. State uses one SQLite
  database and one API worker.

Additional details: `API_README.md`, `FRONTEND_README.md`,
`FLIGHT_INGEST_README.md`, and `MATCHER_README.md`.
