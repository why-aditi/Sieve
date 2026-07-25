"""Price change detection — spec §9.

A step over the threshold that PERSISTS. Persistence is what separates a real
hike from proration, an extra device, or GST rounding.

Three corrections to §9's snippet, all of which change results:

1. `abs(nxt - cur) / cur` divides by zero on a Rs 0 trial charge. A jump up from
   <= Rs 1 is a trial conversion (§10), not a price hike — ground truth tracks
   the two separately, so this returns no PriceChange for it.
2. §9 slices `series[i+1 : i+1+persist]`, which includes the new price itself.
   `abs(nxt - nxt) / nxt` is always 0, so `persist=2` only ever checked ONE
   following charge. The slice has to start at i+2.
3. `periods_per_year` is undefined in §9. It's passed in — it depends on the
   detected period, which this module doesn't compute.
"""

from __future__ import annotations

from models import PriceChange, Transaction

THRESHOLD = 0.05        # 5% — smaller moves are rounding
PERSIST = 2             # charges that must hold at the new price
HOLD_TOLERANCE = 0.02
TRIAL_CEILING = 1.0     # <= Rs 1 opening charge is a trial, not a base price
CREEP_MIN_CHANGES = 3
CREEP_MIN_CUMULATIVE = 0.15


def detect_price_changes(
    txns: list[Transaction], periods_per_year: float = 12.0
) -> list[PriceChange]:
    series = [(t.date, t.amount) for t in sorted(txns, key=lambda x: x.date)]
    changes: list[PriceChange] = []

    i = 0
    while i < len(series) - 1:
        cur, nxt = series[i][1], series[i + 1][1]

        # Trial conversion (Rs 0 -> full price): a dormancy signal, not a hike.
        # Also the divide-by-zero §9 walks straight into.
        if cur <= TRIAL_CEILING:
            i += 1
            continue

        if abs(nxt - cur) / cur > THRESHOLD:
            following = [a for _, a in series[i + 2: i + 2 + PERSIST]]
            held = len(following) >= PERSIST and all(
                abs(a - nxt) / nxt < HOLD_TOLERANCE for a in following
            )
            if held:
                changes.append(PriceChange(
                    from_amount=cur,
                    to_amount=nxt,
                    changed_on=series[i + 1][0],
                    pct=round((nxt - cur) / cur * 100, 2),
                    annual_impact=round((nxt - cur) * periods_per_year, 2),
                    kind="step",
                ))
                i += PERSIST
        i += 1

    return merge_creep(changes)


def merge_creep(changes: list[PriceChange]) -> list[PriceChange]:
    """>=3 same-direction changes totalling >15% is a creep, not N steps (§9)."""
    if len(changes) < CREEP_MIN_CHANGES:
        return changes
    if not all(c.pct > 0 for c in changes) and not all(c.pct < 0 for c in changes):
        return changes
    cumulative = changes[-1].to_amount / changes[0].from_amount - 1
    if abs(cumulative) <= CREEP_MIN_CUMULATIVE:
        return changes
    for c in changes:
        c.kind = "creep"
    return changes


def segments(txns: list[Transaction]) -> list[list[Transaction]]:
    """Split a series at price-change boundaries.

    §8 requires amount stability to be measured PER SEGMENT. Measured across the
    whole series, a genuine hike reads as irregularity and the subscription is
    rejected — which silently halves recall.
    """
    ordered = sorted(txns, key=lambda t: t.date)
    boundaries = {c.changed_on for c in detect_price_changes(ordered)}
    # A trial charge is its own segment: Rs 0 next to Rs 1999 is not instability.
    for i, t in enumerate(ordered):
        if t.amount <= TRIAL_CEILING and i + 1 < len(ordered):
            boundaries.add(ordered[i + 1].date)

    out: list[list[Transaction]] = [[]]
    for t in ordered:
        if t.date in boundaries and out[-1]:
            out.append([])
        out[-1].append(t)
    return [s for s in out if s]
