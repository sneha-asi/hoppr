# Matcher

Install the test dependency and run from this directory:

```sh
python -m pip install -r requirements-test.txt
python -m pytest test_matcher.py -q
```

`matcher.py` uses only the standard library. `Rider` is immutable; its ready time
is a `datetime` (use consistent timezone-aware values), and `solo_fare` is the cab
quote including any night surcharge. `rider_from_demo` accepts the existing JSON
passenger rows and a drop-off-area lookup. When no solo quote is supplied, it
estimates the night surcharge at the rider's ready time.

`match_riders(riders)` returns tuples of rider groups. Parties occupy `party_size`
seats. Group sizes in the scenario tests count bookings, not occupied seats.
Coordinates use great-circle distance with a 12 km inclusive threshold; they
are not road-route distances. Caller code should partition airport pickups before
matching. Gender represents the booking's party for women-only eligibility; supply
`woman` only when all members qualify.

`quote_fare(group)` uses the highest solo quote times 1.15 for shared groups,
divides by occupied seats, then rounds the per-seat charge to the nearest Rs 10
(half-up). Each party pays that charge times its seats. The quote exposes the
unrounded pool price, actual collected amount, and rounding delta. No residual
is added to a rider's bill, because that would break the Rs 10 rounding rule.

`rematch_flight(groups, flight_id, new_eta)` updates the changed flight's riders
to ETA +12 minutes (no large bags) or +22 minutes (with bags). It recomputes only
the groups previously containing those riders, including their former groupmates.
All other group objects remain unchanged. Newly compatible riders in untouched
groups are not recruited; use a full match when that broader behavior is needed.
Re-matching does not refresh solo fare inputs; provide updated quotes separately
if an ETA change crosses a tariff boundary.

The existing generator still uses its original matching heuristic. This module
and its tests implement the subsequently requested 12 km and stricter pairwise
wait rules. The seven saved scenario inputs are reused as regression fixtures.
