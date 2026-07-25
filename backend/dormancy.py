"""Dormancy inference — spec §10.

You cannot see usage from a bank statement. Every signal here is a PROXY and is
labelled as one in the text we hand to the UI, because the alternative — quietly
presenting inference as measurement — is the thing §10 explicitly warns against.

Signals are returned as list[str] to match §5's frozen
`Subscription.dormancy_signals`. Inferred ones carry a "Proxy: " prefix so the
honesty survives all the way to the screen without a parallel field.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal, Optional

from models import MerchantCluster, PriceChange

UsageTap = Literal["yes", "no", "unsure"]

TRIAL_CEILING = 1.0
SILENT_ANNUAL_MIN = 500.0
QUIET_WINDOW_DAYS = 21

WEIGHTS = {
    "trial_conversion": 0.7,
    "silent_annual": 0.6,
    "zombie": 0.5,
    "tap_no": 1.0,
    "tap_unsure": 0.6,   # "can't remember" IS a dormancy signal (§10)
}

# Zombie is only assessable where the statement could plausibly show engagement.
# A bank statement carries no engagement signal for Netflix at all, so firing
# "zombie" there would be a guess wearing the costume of a measurement.
OBSERVABLE_ENGAGEMENT = {"food", "fitness"}


def redundancy_map(clusters: list[MerchantCluster]) -> dict[str, list[str]]:
    """canonical -> same-category peers. Scored by §11's own 0.20 term."""
    by_category: dict[str, list[str]] = {}
    for c in clusters:
        by_category.setdefault(c.category, []).append(c.canonical)
    return {
        c.canonical: sorted(n for n in by_category[c.category] if n != c.canonical)
        for c in clusters
    }


def assess(
    cluster: MerchantCluster,
    period: str,
    price_changes: list[PriceChange],
    all_clusters: list[MerchantCluster],
    redundant_with: list[str],
    tap: Optional[UsageTap] = None,
) -> tuple[float, list[str]]:
    """(score 0-1, human-readable signals).

    Redundancy appears in the signal text but is deliberately NOT scored here —
    §11 gives it a dedicated 0.20 term, and counting it in both places would put
    45% of the score behind one fact and draw two bars for one cause.
    """
    signals: list[str] = []
    weights: list[float] = []

    txns = sorted(cluster.transactions, key=lambda t: t.date)

    # 1. Trial conversion — Rs 0/1 then full price. Classic forgotten signup.
    if len(txns) >= 2 and txns[0].amount <= TRIAL_CEILING < txns[1].amount:
        weights.append(WEIGHTS["trial_conversion"])
        signals.append(
            f"Proxy: started as a Rs {txns[0].amount:.0f} trial on "
            f"{txns[0].date:%d %b %Y}, then went to Rs {txns[1].amount:,.0f}"
        )

    # 2. Silent annual renewal — a large yearly charge with nothing around it.
    if period == "annual" and txns[-1].amount >= SILENT_ANNUAL_MIN:
        window = timedelta(days=QUIET_WINDOW_DAYS)
        renewal = txns[-1].date
        neighbours = [
            t for c in all_clusters if c.canonical == cluster.canonical
            for t in c.transactions
            if t is not txns[-1] and abs((t.date - renewal).days) <= window.days
        ]
        if not neighbours:
            weights.append(WEIGHTS["silent_annual"])
            signals.append(
                f"Proxy: Rs {txns[-1].amount:,.0f} renewed silently on "
                f"{renewal:%d %b %Y} with no related activity for "
                f"{QUIET_WINDOW_DAYS} days either side"
            )

    # 3. Zombie — only where related spend would actually be visible.
    if cluster.category in OBSERVABLE_ENGAGEMENT:
        engaged = any(
            c.category == cluster.category
            and c.canonical != cluster.canonical
            and len(c.transactions) >= 3
            for c in all_clusters
        )
        if not engaged:
            weights.append(WEIGHTS["zombie"])
            signals.append(
                f"Proxy: no other {cluster.category} spending anywhere in the "
                f"statement — nothing suggests you are using it"
            )

    # 4. The user tap. Not a proxy — they told us.
    if tap == "no":
        weights.append(WEIGHTS["tap_no"])
        signals.append("You said you have not used this in the last month")
    elif tap == "unsure":
        weights.append(WEIGHTS["tap_unsure"])
        signals.append("You said you cannot remember using this — that counts")
    elif tap == "yes":
        # The user knows; our proxies do not get to argue with them.
        return 0.0, ["You confirmed you used this in the last month"]

    if redundant_with:
        signals.append(
            f"Duplicate {cluster.category} service alongside "
            f"{', '.join(redundant_with)} (scored separately)"
        )

    # max(), not sum() — a sum exceeds 1.0 and double-penalises. The score is
    # "the strongest evidence we have", which is also what the UI can explain.
    return (max(weights) if weights else 0.0), signals
