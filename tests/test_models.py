"""Typo-catcher for the frozen interface (backend/models.py, spec §5).

Four people code against these structs. If a field gets renamed, this fails here
rather than at hour 10 in someone else's module.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from models import (  # noqa: E402
    Action,
    ExcludedCluster,
    MerchantCluster,
    PriceChange,
    Subscription,
    Transaction,
)


def _txn(day: int, amount: float) -> Transaction:
    return Transaction(
        date=date(2026, 3, day),
        merchant_raw="UPI/NETFLIX BILLDESK/928471/PAYMENT",
        amount=amount,
        direction="debit",
        source="demo",
        source_ref="demo-1",
        account_hint="XX4471",
    )


def test_subscription_constructs():
    cluster = MerchantCluster(
        canonical="Netflix",
        category="streaming",
        raw_variants=["UPI/NETFLIX BILLDESK/928471/PAYMENT", "POS NETFLIX.COM MUMBAI"],
        transactions=[_txn(14, 499.0), _txn(15, 649.0)],
    )
    sub = Subscription(
        cluster=cluster,
        period="monthly",
        period_days=30.5,
        confidence=0.92,
        current_amount=649.0,
        annual_cost=7788.0,
        price_changes=[
            PriceChange(
                from_amount=499.0,
                to_amount=649.0,
                changed_on=date(2026, 3, 15),
                pct=30.06,
                annual_impact=1800.0,
                kind="step",
            )
        ],
        dormancy_signals=["redundant:streaming"],
        leak_score=72.5,
        score_breakdown={"cost": 0.35, "dormancy": 0.25, "redundancy": 0.20},
        action=Action(
            kind="downgrade",
            label="Netflix Premium -> Standard",
            url="https://netflix.com/account",
            menu_path="Netflix -> Account -> Membership -> Change plan",
            est_annual_saving=1800.0,
        ),
        next_charge_date=date(2026, 4, 14),
    )

    assert sub.cluster.canonical == "Netflix"
    assert len(sub.cluster.raw_variants) == 2
    assert sub.price_changes[0].kind == "step"
    assert sub.action.kind == "downgrade"
    assert sub.next_charge_date == date(2026, 4, 14)
    assert sum(sub.score_breakdown.values()) == 0.8


def test_excluded_cluster_constructs():
    excluded = ExcludedCluster(
        cluster=MerchantCluster(
            canonical="Rent",
            category="other",
            raw_variants=["NEFT-RAMESH KUMAR-RENT"],
            transactions=[_txn(1, 18000.0)],
        ),
        reason="rent",
        detail="monthly, Rs 18,000, matches RENT",
    )
    assert excluded.reason == "rent"
    assert excluded.cluster.transactions[0].amount == 18000.0
