"""Leak scoring — spec §11. Arithmetic we display, not a number an LLM emitted.

    leak_score = 100 * (
        0.35 * cost_weight
      + 0.25 * dormancy
      + 0.20 * redundancy
      + 0.15 * unnoticed_hike
      + 0.05 * cheaper_tier
    )

One correction to §11: `cost_weight` divides by the LARGEST subscription, not by
total subscription spend. Dividing by the total caps the term at ~1/n — about
0.28 in a 9-subscription portfolio — which pins the maximum achievable score
near 75 and makes the 81-100 "Cancel" band unreachable. The band table would
then describe a state the engine can never produce. Dividing by the largest
subscription keeps the term explainable ("this is your most expensive one") and
makes all four bands live.
"""

from __future__ import annotations

WEIGHTS = {
    "cost": 0.35,
    "dormancy": 0.25,
    "redundancy": 0.20,
    "unnoticed_hike": 0.15,
    "cheaper_tier": 0.05,
}

# 0-30 Keep · 31-60 Review · 61-80 Downgrade · 81-100 Cancel
BANDS: list[tuple[float, str]] = [
    (30.0, "keep"),
    (60.0, "review"),
    (80.0, "downgrade"),
    (100.0, "cancel"),
]


def band(score: float) -> str:
    for ceiling, name in BANDS:
        if score <= ceiling:
            return name
    return "cancel"


def leak_score(
    annual_cost: float,
    max_annual_cost: float,
    dormancy: float,
    is_redundant: bool,
    has_unnoticed_hike: bool,
    has_cheaper_tier: bool,
) -> tuple[float, dict[str, float]]:
    """(score 0-100, breakdown in POINTS).

    The breakdown values are already weighted and already scaled to 100, so the
    UI's stacked bars sum to the score directly — no second normalisation pass,
    and the "why this score" expander is a straight render of this dict.
    """
    terms = {
        "cost": min(1.0, annual_cost / max_annual_cost) if max_annual_cost else 0.0,
        "dormancy": max(0.0, min(1.0, dormancy)),
        "redundancy": 1.0 if is_redundant else 0.0,
        "unnoticed_hike": 1.0 if has_unnoticed_hike else 0.0,
        "cheaper_tier": 1.0 if has_cheaper_tier else 0.0,
    }
    breakdown = {k: round(100 * WEIGHTS[k] * v, 2) for k, v in terms.items()}
    return round(sum(breakdown.values()), 2), breakdown


def portfolio_score(scored: list[tuple[float, float]]) -> float:
    """Spend-weighted mean of subscription scores (§11).

    `scored` is [(leak_score, annual_cost), ...]. Spend-weighted so a 95-scoring
    Rs 99/month app cannot drag the headline number around.
    """
    total = sum(cost for _, cost in scored)
    if not total:
        return 0.0
    return round(sum(s * cost for s, cost in scored) / total, 1)


def explain(breakdown: dict[str, float]) -> list[str]:
    """One human line per non-zero term, for the 'why this score' expander."""
    labels = {
        "cost": "share of your largest subscription",
        "dormancy": "signs you are not using it",
        "redundancy": "duplicate service in the same category",
        "unnoticed_hike": "price rose without notice",
        "cheaper_tier": "a cheaper tier exists",
    }
    return [
        f"{labels[k]}: +{v:.1f} pts (weight {WEIGHTS[k]:.0%})"
        for k, v in breakdown.items() if v > 0
    ]
