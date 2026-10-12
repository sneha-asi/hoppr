# Hoppr journey reference review

Reviewed 9 October 2026. These are adaptations for airport pooling, not copies of either product.

## Evidence and limits

- [Thine website](https://www.thine.com/): benefit-led introduction with a clear app CTA. Its public website does not expose the complete authenticated onboarding journey.
- [Thine developer's app listing](https://apps.apple.com/us/app/thine-ai/id6757556695): release notes describe core tabs, More for secondary features, and preserving context when switching tabs. Exact first-run screens were not verified.
- [Cityflo developer's app listing](https://apps.apple.com/us/app/cityflo-premium-office-rides/id1060733672): route/timing selection, reserved seats, predictable pricing, wallet/payment options, tracking and ride changes.
- [Cityflo product blog](https://blog.cityflo.com/new-cityflo-flexi-pass/): commuter passes and rescheduling. Passes are a lower priority for occasional airport trips.

## Applied in this HTML iteration

An optional, skippable three-screen welcome explains the benefit, preferences and price lock. New visitors see it once; Home and Profile offer replay. Existing booked riders are not interrupted. No forced login or location request is added.

Keep four primary rider destinations: Home (book), Trips (pickup pass and ride management), Wallet (balance and ledger), Profile (preferences and help). Driver and Ops remain demo workspace controls. Booking stays flight → destination → match; secondary controls stay under More options.

Profile now answers pooling constraints, delay handling, pickup instructions, solo fallback and refund policy. Existing buttons already support Find ride, View ride, Book, Cancel, Refresh and Support. Fare comparison, bags/seats, delay status and data-source labels remain visible at their relevant steps.

## Next priorities requiring product/backend work

1. Verified terminal pickup bays and directions, then genuine driver location with last-update time.
2. A dedicated ride-status view for assigned/en-route/arrived/picked-up/completed states.
3. Authenticated accounts, saved destinations and contextual notification permissions.
4. A payment gateway and explicit production cancellation/refund policy.
5. Route requests and feedback when unsupported destinations or a completed ride occur.

Avoid adding nonfunctional Track driver, Call driver, OTP, rewards or referral buttons. Do not imply identity verification, live transport availability or real settlement. A rides pass should follow evidence of repeat airport usage.
