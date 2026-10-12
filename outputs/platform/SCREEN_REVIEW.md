# Screen review — 9 October 2026

Screenshots are captured by the Playwright journeys at Rider/Driver 390px and
Ops 1440px. The following is a critique of the actual tested layouts, not a
claim of production integration. Full-page images show the fixed bottom bar
at the viewport edge; content remains accessible by scrolling.

| Screen group | Brand / usability assessment |
| --- | --- |
| Rider story 1–4 | One benefit per screen. Pillar illustration, gradient ribbon and purposeful plane/lock icons. Skip and Back avoid an onboarding gate. |
| Rider login | One labelled demo action; accounts are explicitly fictional. Separate application links avoid confusing Rider and Driver jobs. |
| Flights | Delays shown before booking. Repeated rows use consistent heights; imported itinerary is distinct from arrivals. Compact header corrected after its controls originally wrapped to a second line. |
| Flight detail | Scheduled vs estimated arrival, terminal and demo belt are distinct. Amber denotes delay. Pickup/belt assumptions are visible. |
| Booking flight | Confirmed arrival and ready-time explanation; clear single next action. |
| Booking destination | Search, saved places and Pool/Private choices. Special equipment is not promised by an unverified fleet. |
| Booking options | Party/bag/wait fields grouped under More. Women-only attestation is explicit. The form can be longer than one viewport without hiding controls. |
| Matching | Seats are rounded pillars; route divider uses a dashed ribbon. Fare, solo baseline, savings and total are separate. Seat diagram ARIA role was corrected after axe flagged it. |
| Confirmation | Notched boarding pass with large pickup code and locked price. Demo payment disclosure remains near confirmation. |
| Trip | Illustrated route and practical terminal instructions; no fake GPS dot. SOS/call actions clearly describe their local simulation. |
| Rating / receipt | Driver/co-rider feedback and optional mock tip. Receipt uses the same ledger as Ops; illustrative GST is explicitly not a tax invoice. |
| Wallet / More | Balance and refund ledger are distinct from payment methods. Preferences, support threads and privacy controls stay secondary. |
| Support / offline | Native modal traps keyboard focus and closes with Escape. Offline state states that API changes require connection. |
| Driver login / home | Dark default, high contrast, 56px controls. Online toggle, queue and offers precede secondary account information. |
| Driver offer | Large payout before accept, seats/bags and a bounded review timer. The timer is a demo review interaction; expired offers can be reviewed again. |
| Driver accepted / en-route / arrived | One primary stage action. Arrival reveals per-passenger pickup-code inputs. No passenger phone or surname is shown. |
| Driver boarded / summary | Route stages are explicit; completion updates shared booking state. Passenger ratings are optional and persist. |
| Driver earnings / account | Period controls and ledger-derived totals. Documents are visibly synthetic placeholders. Dense details are kept out of the driving stages. |
| Ops command | Calm left rail and compact KPIs. Map is labelled schematic. Unmeasured telemetry is not fabricated. |
| Ops flights / demand | Provider source and fetch timestamps are visible. Forecast is a disclosed scenario based on synthetic banks. |
| Ops pools / profiles | Search, sort, pagination and CSV; record inspector uses readable fields and document cards instead of raw JSON. |
| Ops safety / support | Severity, case status, threads and demo SLA state. Resolve/reply actions are persisted and audited. |
| Ops finance / pricing | Paise values formatted as INR in tables. Reconciliation and wallet liability come from the shared ledger. Pricing previews precede rule saves; locked bookings retain their snapshots. |
| Ops growth / roles | Synthetic planning records and mock permissions are disclosed. Permission restrictions also apply to API exports and actions. |

Remaining design verification: real devices, Hindi content coverage, screen-reader
manual review, all error permutations, physical PWA installation and frame-rate
profiling. Reference APIs and operational services need separate validation.
