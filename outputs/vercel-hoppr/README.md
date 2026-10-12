# Hoppr Vercel demo

Prebuilt React Rider, Driver and Ops apps with a FastAPI serverless entrypoint.
Only synthetic seed records are uploaded; local operational sessions and new
bookings are excluded. No secrets or live provider credentials are bundled.

Deploy from this directory with `vercel --prod --yes` after `vercel login`.

This quick deployment uses writable temporary SQLite storage. It is a presentation
demo: accounts, bookings and edits can reset on cold starts and are not guaranteed
to be shared across server instances. The page labels that limitation explicitly.
Production needs an external persistent database and scheduled ingestion. Live
flight ingestion and background polling are disabled in this hosted package.

Routes: `/rider`, `/driver`, `/ops`, `/docs`, `/deployment-health`.
