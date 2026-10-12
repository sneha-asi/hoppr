"""Pure, immutable airport pool matching and pricing.

No terminal/corridor restriction is imposed; callers should partition pickup
locations beforehand. Distance means great-circle distance, not road distance.
Fares are INR. Per-seat prices use nearest Rs 10, with half-up rounding.
Independent rounding can change the collected total; FareQuote exposes that delta.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Iterable


@dataclass(frozen=True)
class Rider:
    id: str
    ready_time: datetime
    max_wait_min: int
    lat: float
    lng: float
    gender: str
    party_size: int = 1
    large_bags: int = 0
    women_only: bool = False
    solo_fare: Decimal = Decimal('0')
    flight_id: str | None = None

    def __post_init__(self):
        amount = Decimal(str(self.solo_fare))
        object.__setattr__(self, 'solo_fare', amount)
        if not self.id or not isinstance(self.ready_time, datetime):
            raise ValueError('A rider needs an ID and datetime ready_time')
        if any(type(x) is not int for x in (self.party_size, self.large_bags, self.max_wait_min)):
            raise ValueError('Seats, bags and wait must be integers')
        if not 1 <= self.party_size <= 4 or not 0 <= self.large_bags <= 4 or self.max_wait_min < 0:
            raise ValueError('Invalid seats, bags or wait limit')
        if not isfinite(self.lat) or not isfinite(self.lng) or not -90 <= self.lat <= 90 or not -180 <= self.lng <= 180:
            raise ValueError('Invalid coordinates')
        if not amount.is_finite() or amount < 0:
            raise ValueError('Solo fare must be finite and nonnegative')
        if self.women_only and self.gender != 'woman':
            raise ValueError('Only women may request women_only')


Group = tuple[Rider, ...]


def distance_km(a: Rider, b: Rider) -> float:
    x, y = radians(a.lat), radians(b.lat)
    h = sin((y-x)/2)**2 + cos(x)*cos(y)*sin(radians(b.lng-a.lng)/2)**2
    return 6371.0088 * 2 * asin(sqrt(min(1.0, max(0.0, h))))


def compatible(a: Rider, b: Rider) -> bool:
    """Symmetric pair compatibility, including the stricter wait preference."""
    return (
        abs((a.ready_time-b.ready_time).total_seconds()) <= min(a.max_wait_min,b.max_wait_min)*60
        and distance_km(a,b) <= 12.0 + 1e-9
        and (not (a.women_only or b.women_only) or a.gender == b.gender == 'woman')
    )


def fits_cab(riders: Iterable[Rider]) -> bool:
    members = tuple(riders)
    return sum(r.party_size for r in members) <= 4 and sum(r.large_bags for r in members) <= 4


def match_riders(riders: Iterable[Rider]) -> tuple[Group, ...]:
    """Seed earliest unassigned rider, then scan remaining riders in time order.

    Equal ready times are resolved by rider ID. Every new member must be
    compatible with every existing member, including each member's wait limit.
    """
    remaining = sorted(riders, key=lambda r: (r.ready_time,r.id))
    if len({r.id for r in remaining}) != len(remaining):
        raise ValueError('Duplicate rider IDs')
    groups = []
    while remaining:
        group = [remaining[0]]
        rejected = []
        for rider in remaining[1:]:
            if fits_cab((*group,rider)) and all(compatible(rider,m) for m in group):
                group.append(rider)
            else:
                rejected.append(rider)
        groups.append(tuple(group))
        remaining = rejected
    return tuple(groups)


def round_rs10(value: Decimal) -> Decimal:
    return (Decimal(str(value))/10).quantize(Decimal('1'),rounding=ROUND_HALF_UP)*10


@dataclass(frozen=True)
class FareQuote:
    pool_fare: Decimal
    fare_per_seat: Decimal
    allocations: tuple[tuple[str, Decimal], ...]
    collected_total: Decimal
    rounding_delta: Decimal


def quote_fare(group: Group) -> FareQuote:
    """Each booking pays rounded per-seat fare times its occupied seats.

    A single booking (even a party of three) is solo and has no 15% detour.
    solo_fare is the input cab quote, including any applicable night tariff.
    """
    if not group or not fits_cab(group):
        raise ValueError('Fare requires a nonempty group that fits a cab')
    total = max(r.solo_fare for r in group) * (Decimal('1.15') if len(group)>1 else Decimal('1'))
    total = total.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
    per_seat = round_rs10(total/sum(r.party_size for r in group))
    allocations = tuple((r.id,per_seat*r.party_size) for r in group)
    collected = sum((amount for _,amount in allocations),Decimal('0'))
    return FareQuote(total,per_seat,allocations,collected,collected-total)


@dataclass(frozen=True)
class RematchResult:
    groups: tuple[Group, ...]
    affected_rider_ids: tuple[str, ...]
    changed_flight_rider_ids: tuple[str, ...]


def rematch_flight(groups: Iterable[Group], flight_id: str, new_eta: datetime) -> RematchResult:
    """Recompute groups containing riders on the changed flight, and only those.

    All peers in those groups participate in re-matching. Unaffected groups are
    preserved verbatim; this local operation does not recruit riders from them.
    Flight riders become ready ETA+22 min with bags, otherwise ETA+12 min.
    An unknown flight is a no-op. Input riders and groups are never mutated.
    """
    original = tuple(groups)
    ids = [r.id for g in original for r in g]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate rider IDs')
    changed = tuple(r.id for g in original for r in g if r.flight_id == flight_id)
    indices = [i for i,g in enumerate(original) if any(r.flight_id == flight_id for r in g)]
    affected = tuple(r for i in indices for r in original[i])
    updated = tuple(replace(r,ready_time=new_eta+timedelta(minutes=22 if r.large_bags else 12))
                    if r.flight_id == flight_id else r for r in affected)
    replacement = iter(match_riders(updated))
    index_set = set(indices)
    output = []
    for i,g in enumerate(original):
        if i in index_set:
            next_group = next(replacement,None)
            if next_group is not None:
                output.append(next_group)
        else:
            output.append(g)
    output.extend(replacement)
    return RematchResult(tuple(output),tuple(r.id for r in affected),changed)


def rider_from_demo(row: dict, areas: dict, solo_fare=None) -> Rider:
    """Adapt a gen_demo_data.py passenger and area lookup to immutable inputs."""
    area = areas[row['dropoff_area_id']]
    ready = datetime.fromisoformat(row['ready_time'])
    if solo_fare is None:
        multiplier = Decimal('1.2') if ready.hour >= 22 or ready.hour < 6 else Decimal('1')
        solo_fare = Decimal(str(area['day_fare']))*multiplier
    return Rider(id=row['id'],ready_time=ready,max_wait_min=row['max_wait_min'],
                 lat=area['lat'],lng=area['lng'],gender=row['gender'],party_size=row['party_size'],
                 large_bags=row['large_bags'],women_only=row['women_only'],solo_fare=solo_fare,
                 flight_id=row.get('flight_id'))
