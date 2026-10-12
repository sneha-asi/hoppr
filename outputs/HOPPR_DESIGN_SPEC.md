# Hoppr · first refinement

**Scope:** refine the existing static HTML/CSS/JS app and rider journey. Keep
FastAPI, SQLite, working wallet/refunds, notifications, and Driver/Ops views.
The full React onboarding/auth/tracking rebuild is a later phase.

## Brand tokens

Logo pixels sampled directly from the supplied JPEG: indigo `#3330B5`, royal
`#0751E6`, blue `#0496FD`, cyan-blue `#0094F8`, navy `#081C3D`.
Use a 135° indigo → royal → cyan gradient; use navy for text, `#4A5778` for muted
text, `#F3F7FF` for the canvas, and white for surfaces. Dark canvas `#060F24` with
navy surfaces and light text. On-time green; delay amber; errors red. Colour
never carries status alone. Display type: Outfit 800; body: DM Sans; all prices
and times use tabular numerals. Time format: 10:05 PM IST; money: en-IN.

## Components and layouts

- **Ribbon:** gradient road with a dashed white centre line. Use for the booking
  progress and route summary. Animate dashes only during an active request.
- **Pillars:** rounded vertical step/seat/bag indicators, grounded in the logo.
- **Boarding passes:** selected flight and confirmed booking, with perforation
  and notch edges. Show scheduled/estimated times, terminal and explicit source.
- **Rider flow:** select a flight → choose a destination and pool/private preference
  → review the actual API quote and book. Advanced preferences stay under More
  options. Match results explain party seats, bags, group and savings.
- **Confidence:** persist the pickup pass and show the guaranteed booked price.
  Labels distinguish provisional companions, simulated payments, unknown rider
  verification and unconfirmed pickup locations. No invented driver rating.
- **Rider utilities:** Trips, Wallet and Profile views use existing booking and
  wallet state; support remains in More options. Profile preferences are local
  convenience settings, not identity verification.
- **Mobile:** thumb-reachable bottom rider navigation and 44px targets. Desktop
  keeps distinct booking and arrivals columns rather than stretching a phone.
  Driver/Ops remain accessible as their own workspaces.

## Motion and accessibility

Use 250–320ms easing for state changes; request-time ribbon movement and skeleton
loading. Pause decorative motion when idle and disable it under reduced-motion.
Optional haptic feedback only on confirmation and only when supported. Maintain
visible keyboard focus, native labeled inputs, announcements for ETA/errors,
accessible dialog dismissal and semantic tables. Keep text/controls stable during
polling so keyboard focus and expanded details survive unchanged data.

## Verification boundary

Check the rider journey, private/pool choice, price lock, utility views and light/
dark layout at mobile/tablet/desktop widths. Run the full pytest suite and JS
syntax check. Record actual results. Do not claim live airport coverage, verified
identities, real cab availability, payment settlement, Lighthouse scores or a
complete WCAG audit without corresponding evidence.
