# Hoppr frontend

Static, build-free HTML/CSS/JavaScript in `static/`, served at `/` by FastAPI.

```sh
python -m uvicorn api:app --app-dir outputs --workers 1
```

Open http://127.0.0.1:8000/. Requests use same-origin API URLs; opening the HTML
directly as a file is unsupported. The app has Rider, Driver and Ops tabs. Flight
and booking changes poll every 30 seconds while the page is visible. The API
itself polls ingestion every five minutes. The arrivals board identifies its data
source and fixed demo date rather than claiming demo flights are live.

Rider booking has three steps: flight, destination, match. Bags, party size, wait
preference, gender, women-only preference, wallet/payment method, support and
appearance sit under More options. A current match can be restored after reload.
Confirmed fares remain fixed after re-matching, and the pickup pass displays the
four-digit code. ETA notifications produce the requested banner for the rider's
own flight; groupmate changes are labeled as a flight in the pool. Already
dispatched trips ask for coordination instead of falsely claiming re-matching.

Wallets are stored in SQLite and identified by a random browser-local demo ID.
Each new demo wallet starts with Rs 150 credit. Booking atomically applies wallet
balance before the remaining method. UPI/card settlement is simulated; cash is
recorded as due at pickup. No payment gateway or financial account is connected.
If a pool falls through, the rider can keep the guaranteed solo price or use More
options for this ride to cancel before pickup. Paid amounts return to the wallet,
including simulated UPI/card amounts; unpaid cash is not refunded. Refund retries
are idempotent. New endpoints: `GET /wallet?wallet_id=...`, `POST /cancel`, and
`POST /support`. Booking accepts optional `wallet_id` and `payment_method` fields.
Support saves a ticket locally and explicitly says no agent is connected.

Driver controls use confirmed trips and require passenger codes for pickup.
Ops shows actual API booking metrics and the labeled synthetic 14-day history.
Typography pairs Outfit with DM Sans via Google Fonts (system fallbacks
remain usable offline). The supplied Hoppr logo, blue/indigo/cyan runway gradient, rounded pillars, dashed road ribbon and perforated pickup pass define the visual identity. Layout starts at mobile widths and switches to
two columns at 760px. Native form controls, labeled inputs, keyboard-operated
tabs, focus outlines, live regions, a skip link, native support dialog, light/dark
themes and reduced-motion preferences are included.

This is a local demo with wallet IDs, not authenticated user accounts. Real
payments, support delivery, live flight verification and production identity
checks are not included.


The current HTML refinement adds destination search and popular areas, Pool/Private
selection, seat-and-bag occupancy, and Home/Trips/Wallet/Profile rider navigation.
Private rides use the API's optional `ride_type="private"` and remain isolated from
pools after flight changes. Trips and profile preferences use browser-local storage;
wallet ledger entries remain in SQLite. No sign-in or identity verification is implied.
The design scope is recorded in `HOPPR_DESIGN_SPEC.md`. React onboarding and live
trip tracking remain future work. Responsive overflow checks passed at 360, 390,
768, 1280 and 1536 pixels; light and dark themes were visually inspected.


Optional first-visit onboarding is implemented in `static/onboarding.js`, with replay on Home/Profile and pooling, delay, pickup and refund guidance on Profile. Reference evidence and future priorities are in `JOURNEY_LEARNINGS.md`.
