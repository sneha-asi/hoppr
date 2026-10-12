# Hoppr FastAPI demo

From the parent directory containing `outputs`:

```sh
python -m pip install -r outputs/requirements-api.txt
python -m uvicorn api:app --app-dir outputs --workers 1
python -m pytest outputs/test_api.py outputs/test_matcher.py outputs/test_flight_ingest.py -q
```

Open http://127.0.0.1:8000/docs for interactive endpoint documentation. The default
SQLite database is `outputs/airpool_flights.sqlite3`, shared with `flight_ingest.py`.
Set `AIRPOOL_DB` to override its path. Run one worker so ingestion has one owner.
There is no import-time database write; initialization happens in FastAPI lifespan.

Ingestion is **offline by default**, every five minutes. `AIRPOOL_OFFLINE=0` enables
the AeroDataBox → scraper skeleton → demo chain, with `AERODATABOX_KEY` from the
environment. Live calls remain unvalidated. Missing demo rows bootstrap the flights
table; existing ETA values are preserved at startup. The fallback retains fixed
demo dates. The service does not automatically create bookings for the 210 demo
passengers: live demo metrics start at zero and reflect API-created bookings.

## Passenger flow

1. `GET /flights?airport=DEL` returns SQLite flights (16 per airport on a new offline
   database). `GET /destinations?airport=DEL` returns the airport's 12 areas.
2. `POST /match` creates a provisional booking and matches queued requests within
   the same airport and terminal. Use a destination ID or exact area name:

   ```json
   {
     "flight_id": "2026-10-09-DEL-F01",
     "destination": "DEL-A01",
     "bags": 1,
     "party": 1,
     "max_wait": 30,
     "women_only": false
   }
   ```

   Response includes `match_id`, `quote_version`, `group`, `option`,
   `per_seat_fare`, `total_fare` for this party, `solo_fare`, savings in INR and
   percent, and the solo cap. Optional `gender` accepts `woman`, `man`,
   `nonbinary`, or `unknown`. `women_only=true` with omitted gender attests that
   the entire party consists of women; otherwise omitted gender is unknown and
   cannot enter women-only pools. A conflicting gender is rejected.
3. `GET /match/{match_id}` refreshes a quote after another passenger joins or an
   ETA changes. `POST /book` takes:

   ```json
   {"match_id": "ID_FROM_MATCH", "quote_version": 2}
   ```

   The current quote version is required. Stale versions get HTTP 409 rather
   than silently charging a new amount. Successful booking locks the party's
   price, solo-fare baseline, and a random four-digit pickup code. Repeating the
   booking returns the same price/code. Refresh after re-matching to get the
   latest `trip_id`.
4. `GET /notifications?booking_id=...` returns persisted ETA notifications.

### Pricing and availability

The matcher computes max solo fare ×1.15 for a shared group, divided by occupied
seats and rounded to Rs 10 per seat. The API additionally guarantees that a
party's price cannot exceed its solo fare or the **Rs 2,500 per-cab cap**. The cap
is configurable through `create_app(solo_cap=...)`. Ceiling prices are rounded
down per seat to retain Rs 10 multiples and avoid exceeding the cap.

When no pool forms, `/match` still returns a bookable capped solo option.
Confirmed prices remain fixed even if companions never confirm or an ETA change
splits a pool. The demo assumes the platform funds the resulting shortfall; no
payment, subsidy accounting or commercial fare guarantees are implemented.
`solo_fare` for a booked rider is the baseline locked at booking;
`current_solo_fare` reflects current ETA pricing. This prevents historical savings
from changing when fares cross the night/day boundary.

Driver allocation uses available demo vehicles at that airport. All pools fit
four seats/four bags even if assigned an SUV. If drivers are exhausted, booking
still locks a price and reports `awaiting_driver`; this is a priced option, not a
guarantee of immediate vehicle supply. Quoted companions are provisional. At
dispatch they are removed from the confirmed trip and receive separate quotes.
Confirmed rider charges never change.

## Driver flow

`GET /driver/trip` returns active trips with confirmed bookings. Optional
`trip_id` and `driver_id` filters narrow the list. It excludes provisional riders
and does not expose their pickup codes. `POST /driver/step` takes `trip_id` and
`step`, in this order:

`queued → en_route → arrived → picked_up → completed`

For `picked_up`, also pass all confirmed booking IDs and passenger-provided codes:

```json
{
  "trip_id": "TRIP_ID",
  "step": "picked_up",
  "pickup_codes": {"BOOKING_ID": "1234"}
}
```

Invalid transitions return 409; missing/incorrect codes return 422. Retrying the
current step is idempotent. Completion releases the vehicle. Already-dispatched
trips are not re-pooled after an ETA change; notifications request coordination.

## Operations and ETA re-matching

`GET /ops/summary` includes current and completed API bookings: cabs needed,
active cabs, awaiting-driver count, fewer cars percent, aggregate rider savings,
and average people per cab. Fewer cars compares one separate cab **per booking**
(a party of three counts as one baseline cab). Average riders counts occupied
seats. Provisional quotes are excluded. `history_14_days` contains the supplied
synthetic history using the generator's original matching/pricing; its source is
explicitly labeled.

Every ingestion tick upserts flights, then consumes durable SQLite `changes`.
Only queued groups containing changed-flight bookings are re-matched, including
their groupmates, using `matcher.rematch_flight`. Ready times and current solo
quotes update; locked prices survive. Notifications and the processed change
cursor commit together so pending changes are processed after a restart without
duplicate notifications. Unaffected group IDs remain untouched by ETA processing.

The static frontend is served at `/`. See `FRONTEND_README.md` for the demo
wallet, payment simulation, cancellation/refund and support-ticket endpoints.

This is a local demo API without authentication, quote expiration, external
payment processing, or real driver dispatch. Each `/match`
creates a new provisional request. Use one request per rider and refresh its
returned ID; do not retry `/match` to refresh a quote. `POST /book` retries are
idempotent. Tests use isolated SQLite databases and fake/offline providers.

`POST /match` also accepts optional `ride_type`, either `pool` (default) or `private`.
Private requests create a cab for their own party and are excluded from pooled
matching, including re-matching after flight ETA changes. The same solo price cap
and booking price lock apply.
