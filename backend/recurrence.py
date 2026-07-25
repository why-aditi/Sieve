"""Recurrence detection — spec §8. Pure arithmetic on dates and amounts.

Two independent signals, combined with max():

  A. regularity  — MAD of inter-arrival deltas
  B. anchoring   — how tightly charges cluster on one day of the month

Why max() and not a blend: a monthly subscription drifts around weekends and
short months, so raw deltas look noisy (30, 31, 28, 31 gives a MAD that reads
badly against a 28-day month). But if every charge lands on day 14 +/- 2, that is
strong independent evidence. Taking the max recovers subscriptions that pure
delta-regularity rejects — this is the signal most implementations miss.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal, Optional

from models import Transaction
from price_change import segments

PERIOD_BANDS: dict[str, tuple[int, int]] = {
    "weekly": (5, 9),
    "monthly": (28, 32),
    "quarterly": (88, 95),
    "annual": (355, 370),
}
PERIODS_PER_YEAR = {"weekly": 52.0, "monthly": 12.0, "quarterly": 4.0, "annual": 1.0}

MIN_OCCURRENCES = 3
# 18 months of statement cannot contain 3 annual charges — for ANY real user,
# not just synthetic ones. Holding annual subs to >=3 drops every one of them,
# including the "forgotten annual renewal" §13 asks us to surface.
ANNUAL_MIN_OCCURRENCES = 2
TWO_POINT_CONFIDENCE_CAP = 0.6   # one delta is weak evidence; don't claim 1.0
MAX_SEGMENT_CV = 0.35            # above this it's a variable bill, not a plan
# Confidence is the whole point of §8's two signals — so gate on it. Frequent
# noise (78 food-delivery charges, median gap 5 days) snaps to the weekly band
# on median delta alone, but scores 0.0 regularity and 0.0 anchoring. Without
# this floor that noise is reported as a weekly subscription.
MIN_CONFIDENCE = 0.5


@dataclass
class Recurrence:
    period: Literal["weekly", "monthly", "quarterly", "annual"]
    period_days: float
    confidence: float
    regularity: float
    anchor: float
    amount_stability: float
    occurrences: int
    current_amount: float
    annual_cost: float
    next_charge_date: Optional[object]  # datetime.date


def snap_to_period(median_days: float) -> Optional[str]:
    for period, (lo, hi) in PERIOD_BANDS.items():
        if lo <= median_days <= hi:
            return period
    return None


def amount_stability(txns: list[Transaction]) -> float:
    """Coefficient of variation, computed PER PRICE SEGMENT (§8), then medianed.

    Across the whole series a real hike registers as instability; within a
    segment it doesn't. The trial charge is its own segment for the same reason.
    """
    cvs = []
    for seg in segments(txns):
        amounts = [t.amount for t in seg]
        mean = statistics.fmean(amounts)
        if len(amounts) < 2 or mean <= 1.0:
            continue
        cvs.append(statistics.pstdev(amounts) / mean)
    return statistics.median(cvs) if cvs else 0.0


def detect_recurrence(txns: list[Transaction]) -> Optional[Recurrence]:
    if len(txns) < ANNUAL_MIN_OCCURRENCES:
        return None

    dates = sorted(t.date for t in txns)
    deltas = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    if not deltas:
        return None
    med = statistics.median(deltas)

    period = snap_to_period(med)
    if period is None:
        return None

    min_required = ANNUAL_MIN_OCCURRENCES if period == "annual" else MIN_OCCURRENCES
    if len(txns) < min_required:
        return None

    # Signal A: regularity
    mad = statistics.median([abs(d - med) for d in deltas])
    regularity = max(0.0, 1.0 - (mad / med) * 3) if med else 0.0

    # Signal B: day-of-month anchoring — the trick most teams miss
    anchor = 0.0
    if period == "monthly":
        doms = [d.day for d in dates]
        centre = statistics.median(doms)
        spread = statistics.median([abs(x - centre) for x in doms])
        anchor = max(0.0, 1.0 - spread / 4)

    confidence = max(regularity, anchor)
    if len(txns) == 2:
        confidence = min(confidence, TWO_POINT_CONFIDENCE_CAP)
    if confidence < MIN_CONFIDENCE:
        return None

    stability = amount_stability(txns)
    if stability > MAX_SEGMENT_CV:
        return None  # variable-amount bill (electricity, card autopay)

    ordered = sorted(txns, key=lambda t: t.date)
    current = ordered[-1].amount
    per_year = PERIODS_PER_YEAR[period]

    return Recurrence(
        period=period,
        period_days=float(med),
        confidence=round(confidence, 3),
        regularity=round(regularity, 3),
        anchor=round(anchor, 3),
        amount_stability=round(stability, 4),
        occurrences=len(txns),
        current_amount=current,
        annual_cost=round(current * per_year, 2),
        next_charge_date=_next_charge(dates[-1], med),
    )


def _next_charge(last, median_days: float):
    from datetime import timedelta
    return last + timedelta(days=round(median_days))
