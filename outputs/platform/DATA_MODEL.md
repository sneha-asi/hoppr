# Shared Hoppr model

All three apps use one SQLite database, integer paise for money, ISO-8601 timestamps
with offsets, synthetic identity records and stable string primary keys. The demo
clock is 9 October 2026, 20:00 IST. Road distances, bay locations and all tariffs
are planning assumptions. The 60-day booking archive requires flights older than
the requested 14-day visible arrivals history; those remain linked archive rows.

| Table | Key and relationships |
| --- | --- |
| airports | id=IATA; terminals, pickup instructions, hand-set destinations |
| flights | id; airport_id → airports; schedule, ETA, status/source |
| flight_updates | id; flight_id → flights; successive ETA observations |
| riders | id; synthetic first name, persona, preferences, saved places |
| drivers | id; airport_id → airports; documents, availability, payout-mask |
| cabs | id; driver_id → drivers; seats, bags, insurance |
| pools | id; flight cohorts; driver_id → drivers; cab_id → cabs; pickup/end |
| bookings | id; rider_id → riders; flight_id → flights; pool_id → pools; destination |
| payments | id; booking_id → bookings (unique); fare, fees, tax, refunds and payout |
| wallet_entries | id; rider_id → riders; booking_id → bookings (nullable); signed paise |
| ratings | id; booking_id → bookings; author direction, score, text, tip |
| tickets | id; rider_id → riders; booking_id → bookings (nullable); thread and SLA |
| incidents | id; pool_id → pools; severity, resolution, timeline |
| ops_users | id; role, synthetic identity |
| audit | id; ops_user_id → ops_users; action, entity and timestamp |
| promos, passes, referrals, demand_requests | synthetic growth records with linked rider IDs |
| notifications | id; audience, entity, text, source/ETA timestamp |

Financial convention: transport fare is split 80% driver / 20% platform; Rs 19
service fee per occupied seat belongs to the platform; illustrative 5% GST is
added to transport plus service fee. Collected minus refunds equals driver payout
plus total platform revenue plus tax. This is a demo tax convention, not tax advice
or a GST-compliant invoice. Cancelled trips have full refunds and zero net payout.
Wallet and promo funding are tender components, not extra revenue. No real bank,
phone, identity documents or customer data are stored.

Every payload has schema version 2. Typed relationship columns and foreign keys
are relational; JSON holds display metadata. Production migration should promote
metadata fields to typed columns and replace the mock session boundary.
