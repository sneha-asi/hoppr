# Live deployment

Published and verified 9 October 2026:

- Rider: https://vercel-hoppr.vercel.app/rider
- Driver: https://vercel-hoppr.vercel.app/driver
- Ops: https://vercel-hoppr.vercel.app/ops

Vercel deployment: `dpl_FEcZ2agypVL5z66nRdxiZuazwqdM` (READY, production).

Verified HTTP 200 for all three app pages, deployment health and airports.
Demo sign-in and the DEL arrivals API returned successfully with 25 flights.
Live Rider onboarding rendered in the browser.

Hosted demo account selectors now work across server instances. Roles are derived
from the stored demo account; this remains public mock sign-in, not production
authentication. Verified across two independent local databases and live repeated
profile requests, matching, booking and ride retrieval.

Hosted demo uses temporary SQLite state: bookings and edits may reset or differ
across server instances. Live flights, payments and GPS remain simulated.
