# Hoppr — three apps, one operation

React / Vite / TypeScript / Framer Motion clients share one FastAPI backend,
one SQLite database and one design-token file. The earlier static demo in the
parent `outputs/` directory is retained separately.

## Open the apps

- Rider: http://127.0.0.1:8010/rider
- Driver: http://127.0.0.1:8010/driver
- Ops: http://127.0.0.1:8010/ops
- API docs: http://127.0.0.1:8010/docs

Each has its own mock session. Rider defaults to Meera (`demo@hoppr.app`, R0001),
Driver to D004, and Ops to admin O1. Additional accounts can be selected at login.
The labels **Demo data. Not real people.** and **Demo snapshot** are intentional.
There are no production credentials, real payments, real documents or live GPS.

To see the same trip in all three apps, book a Rider trip, inspect its assigned
driver reference in Ops → Bookings, and sign in to that Driver account. Accept,
arrive, verify the rider's code and complete the trip. Refresh Rider Trips to rate
and view the receipt. Bookings, refunds, tips and earnings update the same ledger.

## Setup

Python 3.11 and Node 24 were used here. From the supplied workspace root:

```powershell
python -m pip install -r outputs/requirements-api.txt
cd outputs/platform/web
npm ci
npm run build
cd ../../..
python -m uvicorn backend:app --app-dir outputs/platform --host 127.0.0.1 --port 8010 --workers 1 --no-proxy-headers
```

The delivered JSON and database already contain the seed. To generate **fresh**
files without replacing operational data:

```powershell
python outputs/platform/gen_demo_data.py --seed 20261009 --output work/new-demo.json --db work/new-demo.sqlite3
```

Generation refuses an existing populated database. Use another path and preserve
any bookings you need before switching the server's database. The synthetic clock
is **9 October 2026, 20:00 IST**. Flight boards offer today and the next two days.
Older flights are linked archive rows, necessary for the 60-day trip history.
The visible arrivals window is last 14 days plus next three; API queries can also
retrieve archived dates.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOPPR_V2_DB` | `platform/hoppr.sqlite3` | Shared v2 database; separate from the original static demo. |
| `AIRPOOL_OFFLINE` | `1` | Demo-only ingestion. Exactly `0` enables the unverified provider chain. |
| `AERODATABOX_KEY` | unset | RapidAPI credential, read by the existing AeroDataBox provider. Never logged. |
| `PLAYWRIGHT_BROWSERS_PATH` | configured in test config | Browser install path. This workspace uses `work/pw-browsers`. |
| `HOPPR_E2E_EXTERNAL` | unset | Use an already-running isolated test server at port 8011. Useful on Windows hosts whose runner cannot terminate child servers. |
| `HOPPR_AUDIT_URL` | `http://127.0.0.1:8010` | Target for the included Lighthouse script. |

One worker owns the 30-second provider poll and process-local arrival cache/rate
limiter. `/v2/flights` caches each airport/date for 10 seconds and allows 60
requests per client per minute. `/v2/health` reports persisted last-success/source
records. The chain reuses `../flight_ingest.py`: AeroDataBox → scraper skeleton →
shared-dataset fallback. Provider failures use its structured safe logging. API
field assumptions remain marked `TODO(verify)` there. The shared fallback reads
the SQLite seed and does not reset simulated ETA changes. ETA simulations are
available through Ops flight details; queued affected groups are re-matched,
booked prices are retained, and Rider/Driver/Ops receive notifications.

## Data and financial conventions

See `DATA_MODEL.md`. Seed 20261009 contains 800 riders, 120 drivers and cabs,
4,725 synthetic flights, 14,175 ETA observations, **6,158 pools**, **12,551 bookings
and payments**, 300 support tickets, 25 incidents and six Ops accounts.
Solo share is **35.48%**; exact distributions are in `validation-report.json`.
Actual greedy matching creates every archive pool, partitioned by terminal.
Driver allocation checks trip overlap and a 15-minute rest interval.

All cash values are integer paise. Transport is split per occupied seat and
rounded to Rs 10. New quotes cap transport at the solo baseline / Rs 2,500 and
round the cap down per seat. Rs 19/seat service and illustrative 5% GST are
additional, visible charges. Archive fare generation follows the raw matcher
formula. Driver share defaults to 80% of transport; tips belong to the driver.
Platform revenue includes its 20% transport share plus the service fee. Net
collection equals driver payout + platform revenue + tax. Demo promo funding is
a tender component, not another charge. A voluntary tip does not change the
locked transport fare. Refund records remove payout/revenue/tax and credit
eligible paid amounts to the wallet; unpaid cash and promo funding are excluded
from wallet refunds on new cancellations.

The ledger allocates demo earnings at booking; it is not bank settlement.
Opening wallet credit is synthetic funding. Pass sales and referral records are
planning data; no automatic pass purchase, incentive payout or cashback happens.
Pricing edits affect new quotes and retain booked snapshots; each change is audited.

## Verified on 9 October 2026

- **88 pytest tests pass**, including the original 67 tests, data invariants,
  corruption detection, deterministic generation, foreign keys, role boundaries,
  price locks, private groups, ETA re-matching, wallet/refund/tip reconciliation,
  driver stages and per-passenger code verification.
- **Five Playwright tests pass**: Rider-to-Driver full journey, Ops modules with
  sort/filter/export/resolution, responsive/support/PWA-offline checks, and the
  illustrated airport workspace with interactive phone/laptop icon controls, and
  Rider Trips/Wallet/Profile plus Driver dashboard at 360/390/768/1440px.
- React TypeScript production build succeeds. Screenshots are in `screenshots/`;
  visual critique is in `SCREEN_REVIEW.md`.
- Automated axe checks target WCAG A/AA on tested Rider, Driver and Ops views.
  They are not a complete accessibility certification.
- Lighthouse reports and scores are saved in `lighthouse-*.json` and
  `lighthouse-summary.json`. Measurements are localhost lab runs, not field data.
  Final performance scores: Rider 100, Driver 100, Ops 99; automated accessibility
  scores were 100 for each app.
- Rider and Driver have separate PWA identities, PNG icons and a service worker
  that caches the app shell while excluding account/API data. Offline shell
  behavior was tested; installing on every mobile OS was not.

```powershell
python -m pip install -r outputs/requirements-test.txt
python -m pytest outputs -q --junitxml=outputs/platform/full-test-results.xml
cd outputs/platform/web
$env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path ../../../work/pw-browsers).Path
npx playwright install chromium
npm run test:e2e
node tests/lighthouse.mjs
```

Playwright copies the seed into `work/platform-e2e.sqlite3`; it never modifies the
user-facing database. For an external test server, first copy the seed to that
path, start Uvicorn on 8011 with `HOPPR_V2_DB` pointing there, then set
`HOPPR_E2E_EXTERNAL=1` for the runner. Keep the test database isolated.

## Unverified or intentionally simulated

Live AeroDataBox responses, real fares/tax treatment, measured road routes,
authorised pickup bays, baggage belts, geofences, demand predictions, driver GPS,
masked calling, emergency response, payment gateways, bank payouts and real
identity/documents are not verified integrations. The lock-screen card is a
preview, not an OS Live Activity. SOS creates a local incident, never an emergency
call. Accessibility/child-seat requests require support confirmation and cannot
be silently booked. Quiet ride is a preference, not a guarantee.

Hindi covers core navigation/booking controls; the entire interface and support
content are not fully translated. Passes, referral funding, waiting/toll charges,
incentives, training video playback, route deviation telemetry and cohort
retention remain previews or unmeasured planning data. No 60fps field measurement
or real-device installation matrix has been run. Mock session/role controls are
not production security. SQLite foreign keys provide relational consistency;
a PostgreSQL migration and production reconciliation have not been executed.
