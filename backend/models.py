"""Frozen interface — spec docs/prd.md §5.

Every field name here is load-bearing: the whole team codes against these.
Do not rename anything without telling everyone.

Additions to §5 (agreed, purely additive — no §5 field was changed):
  - Action           §5 forward-references it but never defines it. Shape from §12.
  - ExcludedCluster  §15's "correctly excluded" panel needs a reason per reject.
  - Subscription.next_charge_date  §15's dashboard table has a "next charge" column.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional


@dataclass
class Transaction:
    date: date
    merchant_raw: str           # "UPI/NETFLIX BILLDESK/928471/PAYMENT"
    amount: float               # always positive
    direction: Literal["debit", "credit"]
    source: Literal["demo", "sms_paste", "sms_xml", "gmail", "csv"]
    source_ref: Optional[str]   # message id / row index, for the audit trail
    account_hint: Optional[str]  # "XX4471"


@dataclass
class PriceChange:
    from_amount: float
    to_amount: float
    changed_on: date
    pct: float
    annual_impact: float
    kind: Literal["step", "creep"]


@dataclass
class Action:
    kind: Literal["cancel", "downgrade", "renegotiate", "keep"]
    label: str                   # "Cancel Netflix Premium"
    url: Optional[str]           # deep link to the cancellation page
    menu_path: Optional[str]     # "Netflix -> Account -> Membership -> Cancel"
    est_annual_saving: float


@dataclass
class MerchantCluster:
    canonical: str              # "Netflix"
    category: str               # "streaming"
    raw_variants: list[str]     # the 4 strings that collapsed into this
    transactions: list[Transaction]


@dataclass
class Subscription:
    cluster: MerchantCluster
    period: Literal["weekly", "monthly", "quarterly", "annual"]
    period_days: float
    confidence: float           # 0-1, from regularity + anchoring
    current_amount: float
    annual_cost: float
    price_changes: list[PriceChange]
    dormancy_signals: list[str]
    leak_score: float           # 0-100
    score_breakdown: dict[str, float]
    action: Action
    next_charge_date: Optional[date]


@dataclass
class ExcludedCluster:
    cluster: MerchantCluster
    reason: Literal["rent", "salary", "emi", "sip", "cc_bill", "utility"]
    detail: str                 # "monthly, Rs 18,000, matches RENT" - shown in the UI
