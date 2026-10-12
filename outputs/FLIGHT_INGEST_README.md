# Flight ingestion scaffold

Live calls have **not been tested or validated**. API response-field assumptions
are marked `TODO(verify)` in the implementation and the hand-written test fixture.
Endpoint/header configuration follows the official documentation:
https://doc.aerodatabox.com/rapidapi.html and
https://aerodatabox.com/realtive-fids/.

```sh
python flight_ingest.py --offline --once
python flight_ingest.py --offline
python -m pytest test_flight_ingest.py -q
```

Default database: `airpool_flights.sqlite3` next to the script. Override with
`--db PATH`; override the fallback file with `--demo PATH`. Without `--once`,
polls start every 300 seconds (or immediately after a poll taking longer than
that). Ctrl+C stops polling. `--offline` constructs only the demo provider and
never attempts HTTP or scraping. Demo flights keep their fixed dates and original
IDs for compatibility with passenger flight references; they are not live arrivals.

The online provider chain runs separately for DEL, BOM and BLR: AeroDataBox,
scraper skeleton, demo JSON. Set `AERODATABOX_KEY` in the environment to configure
RapidAPI authentication. Requests use `offsetMinutes=-30`, `durationMinutes=240`,
`direction=Arrival`, and `withLeg=true` to request origin information. A valid
empty arrival list counts as a successful response, so no demo rows are added.
Malformed response data or provider failures try the next provider. The scraper
always raises `NotImplementedError`; check each site's terms and robots.txt before
implementing it.

Normalized times are offset-aware UTC ISO strings. Unknown origin/airline/terminal
values remain null. Missing ETA defaults to scheduled time. Negative delays denote
early arrival. Rows include an explicit `source` so synthetic fallback data remains
identifiable. Live IDs use airport, flight number and scheduled local arrival date;
confirm duplicate-leg/codeshare identity handling with real responses.

`upsert_flights(connection, rows)` atomically stores normalized rows and returns
the unique IDs whose ETA changed. Initial inserts and status-only updates create
no change event. `changes` stores old/new ETA, observation time and source. Times
with different offsets but the same instant count as unchanged. `poll_once` returns
changed IDs across airports, suitable for looking up ETA and calling the matcher;
it does not invoke re-matching itself. Flight deletion/pruning, provider identity
reconciliation, and dispatch integration are outside this scaffold.
