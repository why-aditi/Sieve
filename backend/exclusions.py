"""Exclusion filter — spec §8.1.

Rent, salary, EMIs, SIPs, card bills and utilities are perfectly periodic and are
NOT subscription leaks. Getting this right is a feature we show (§15's "correctly
excluded" panel), not a bug we hide — every competing demo will confidently tell
the user to cancel their rent.

Deliberate ordering change from §4: exclusions run BEFORE recurrence detection,
not after. §4's diagram puts them last, but a decoy that fragments across raw
templates may not survive the recurrence gate at all — and would then vanish
silently instead of appearing in the excluded panel. Keyword classification
doesn't need a detected period, so running it first is both cheaper and more
honest.
"""

from __future__ import annotations

import re

from models import ExcludedCluster, MerchantCluster
from normalize import clean

# Matched against the CLEANED string, so "ACH-D- HDFCLOAN EMI 795145" is already
# "HDFCLOAN EMI" by the time we look at it.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "emi": ("EMI", "LOAN", "HDFCLOAN", "SBILOAN", "ICICILOAN", "BAJAJFIN",
            "BAJAJ", "FINSERV", "HDBFS", "HDB FINANCIAL"),
    "sip": ("SIP", "MF", "GROWW", "ZERODHA", "KUVERA", "NIPPON", "COIN",
            "MUTUAL FUND", "BLUECHIP"),
    "cc_bill": ("CC PAYMENT", "CARD PAYMENT", "AUTOPAY", "CREDIT CARD"),
    "utility": ("BESCOM", "MSEB", "MAHADISCOM", "TATA POWER", "TATAPOWER",
                "ELECTRICITY", "WATER BOARD", "GAS BILL", "BILL PAYMENT",
                "TNEB", "BSES", "TORRENT POWER"),
    "rent": ("RENT", "LANDLORD", "MAINTENANCE CHARGES"),
}

RENT_MIN_AMOUNT = 5000.0
ORDER = ("salary", "emi", "sip", "cc_bill", "utility", "rent")


def _matches(keyword: str, blob: str) -> bool:
    """Keyword must start at a word boundary.

    Plain substring matching flags YOUTUBE-PR-EMI-UM as a loan EMI, which drops a
    real subscription. A trailing boundary is deliberately NOT required: bank
    strings glue suffixes on ("BESCOMBLR", "TATAPOWERDL", "HDFCLOAN"), and those
    must still match their keyword.
    """
    return re.search(r"\b" + re.escape(keyword), blob) is not None


def classify(cluster: MerchantCluster) -> tuple[str, str] | None:
    """(reason, detail) if this cluster must be excluded, else None."""
    # Salary is structural, not lexical: money coming in is never a subscription.
    if any(t.direction == "credit" for t in cluster.transactions):
        total = sum(t.amount for t in cluster.transactions)
        return "salary", (
            f"credit, {len(cluster.transactions)} received, "
            f"Rs {total:,.0f} total"
        )

    blobs = [clean(v) for v in cluster.raw_variants] + [cluster.canonical.upper()]
    amounts = [t.amount for t in cluster.transactions]
    avg = sum(amounts) / len(amounts) if amounts else 0.0

    for reason in ORDER:
        if reason == "salary":
            continue
        for kw in KEYWORDS[reason]:
            if any(_matches(kw, b) for b in blobs):
                if reason == "rent" and avg < RENT_MIN_AMOUNT:
                    continue  # §8.1: rent is monthly AND large
                return reason, _detail(reason, kw, cluster, avg)
    return None


def _detail(reason: str, kw: str, cluster: MerchantCluster, avg: float) -> str:
    spread = max(t.amount for t in cluster.transactions) - min(
        t.amount for t in cluster.transactions)
    variable = " variable amount," if spread > avg * 0.05 else " fixed amount,"
    return (
        f"{len(cluster.transactions)} charges,{variable} avg Rs {avg:,.0f}, "
        f"matched '{kw}'"
    )


def split(
    clusters: list[MerchantCluster],
) -> tuple[list[MerchantCluster], list[ExcludedCluster]]:
    """(kept, excluded). Excluded items carry their reason — we display them."""
    kept: list[MerchantCluster] = []
    excluded: list[ExcludedCluster] = []
    for c in clusters:
        verdict = classify(c)
        if verdict is None:
            kept.append(c)
        else:
            reason, detail = verdict
            excluded.append(ExcludedCluster(cluster=c, reason=reason, detail=detail))
    return kept, excluded
