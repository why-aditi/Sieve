"""Cross-source deduplication — spec §6.7.

Multi-source means the same charge arrives twice: an email receipt from the
merchant and a bank SMS for the same debit. Match on:

    amount within Rs 1  ·  date within 24h  ·  merchant fuzzy ratio > 80

Keep the record with the richer merchant string, and retain both source refs so
the audit trail survives the merge.

Bucketed by rounded amount rather than compared pairwise. 800x800 would be fine,
but this is the multi-source path — 5,000 SMS against 5,000 emails is 25M
comparisons, and that is the case the feature exists for.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from rapidfuzz import fuzz

from models import Transaction
from normalize import clean, resolve

AMOUNT_TOLERANCE = 1.0
DATE_TOLERANCE = timedelta(hours=24)
MERCHANT_RATIO = 80

# Source preference when two records describe the same charge. Email receipts
# carry the merchant's own name ("Netflix"); bank SMS carries the payment-rail
# string ("UPI/NETFLIX BILLDESK/928471/PAYMENT"). The SMS string is uglier but
# it is what the normalizer's alias table is built against, so it wins ties.
SOURCE_RANK = {"sms_xml": 4, "sms_paste": 4, "csv": 3, "gmail": 2, "demo": 1}


@dataclass
class DedupReport:
    merged: int
    kept: int
    pairs: list[tuple[str, str]]   # (kept merchant, dropped merchant)


def _richer(a: Transaction, b: Transaction) -> tuple[Transaction, Transaction]:
    """(winner, loser). Richer = more information the normalizer can use."""
    a_key = (SOURCE_RANK.get(a.source, 0), len(clean(a.merchant_raw)))
    b_key = (SOURCE_RANK.get(b.source, 0), len(clean(b.merchant_raw)))
    return (a, b) if a_key >= b_key else (b, a)


def _same_charge(a: Transaction, b: Transaction) -> bool:
    # §6.7 is about ONE charge arriving from two sources. Two records from the
    # same source are two charges: a person really can order from Zomato twice
    # on a Friday for the same amount, and collapsing those would delete a real
    # transaction rather than a duplicate one.
    if a.source == b.source:
        return False
    if a.direction != b.direction:
        return False
    if abs(a.amount - b.amount) > AMOUNT_TOLERANCE:
        return False
    if abs(a.date - b.date) > DATE_TOLERANCE:
        return False
    # §6.7 says "merchant fuzzy ratio > 80", and that alone is not enough: an
    # email says "Google One" while the bank says "UPI/GOOGLEONE/373610/PAYMENT",
    # and spaced-vs-glued defeats token_set_ratio (no shared token at all).
    # We already own a merchant resolver, so ask it first — two strings that
    # resolve to the same brand ARE the same merchant. Fuzzy stays as the
    # fallback for merchants the alias table doesn't know.
    a_canon, _, a_method = resolve(a.merchant_raw)
    b_canon, _, b_method = resolve(b.merchant_raw)
    if a_method in ("alias", "fuzzy") and b_method in ("alias", "fuzzy"):
        return a_canon == b_canon

    return fuzz.token_set_ratio(clean(a.merchant_raw), clean(b.merchant_raw)) > MERCHANT_RATIO


def _merge(winner: Transaction, loser: Transaction) -> Transaction:
    refs = [r for r in (winner.source_ref, loser.source_ref) if r]
    return replace(
        winner,
        source_ref="+".join(dict.fromkeys(refs)) or None,
        account_hint=winner.account_hint or loser.account_hint,
    )


def dedup(txns: list[Transaction]) -> tuple[list[Transaction], DedupReport]:
    """Collapse duplicate charges across sources. Order-stable by date."""
    ordered = sorted(txns, key=lambda t: (t.date, t.merchant_raw))

    buckets: dict[int, list[int]] = {}
    out: list[Transaction | None] = list(ordered)
    pairs: list[tuple[str, str]] = []
    merged = 0

    for i, txn in enumerate(ordered):
        key = round(txn.amount)
        # A charge of 100.4 and one of 99.7 are within Rs 1 but round to
        # different buckets, so every neighbour bucket has to be checked.
        hit = None
        for probe in (key - 1, key, key + 1):
            for j in buckets.get(probe, ()):
                if out[j] is not None and _same_charge(out[j], txn):
                    hit = j
                    break
            if hit is not None:
                break

        if hit is None:
            buckets.setdefault(key, []).append(i)
            continue

        winner, loser = _richer(out[hit], txn)
        out[hit] = _merge(winner, loser)
        out[i] = None
        pairs.append((winner.merchant_raw, loser.merchant_raw))
        merged += 1

    kept = [t for t in out if t is not None]
    return kept, DedupReport(merged=merged, kept=len(kept), pairs=pairs)
