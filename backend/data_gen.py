"""Synthetic transaction generator — spec §13.

Emits, per profile: transactions.json, ground_truth.json, sms.txt, emails.json.

This corpus is three things at once: the judge's demo data (§6.2), the labelled test
set for the eval harness (§14), and the stress test for the merchant normalizer (§7).

Two determinism rules, both load-bearing:
  - random.Random(seed) per profile, never bare random
  - END_DATE is a constant, never date.today()
Break either and the committed corpus stops matching its own ground truth.

Run:  python data_gen.py
"""

from __future__ import annotations

import calendar
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional

from dateutil.relativedelta import relativedelta

END_DATE = date(2026, 7, 20)
MONTHS = 18
START_DATE = END_DATE - relativedelta(months=MONTHS)
TARGET_TXNS = 800
OUT_DIR = Path(__file__).resolve().parents[1] / "data"

CITIES = ["MUMBAI", "BENGALURU", "PUNE", "DELHI", "HYDERABAD", "CHENNAI", "GURGAON"]


# --------------------------------------------------------------------------- specs


@dataclass
class SubSpec:
    canonical: str
    category: str
    amount: float
    period: Literal["weekly", "monthly", "quarterly", "annual"]
    anchor_day: int
    templates: list[str]
    anomaly: Optional[dict] = None


@dataclass
class DecoySpec:
    canonical: str
    reason: Literal["rent", "salary", "emi", "sip", "cc_bill", "utility"]
    amount: float
    anchor_day: int
    templates: list[str]
    direction: Literal["debit", "credit"] = "debit"
    varies: float = 0.0  # fractional swing; >0 means variable amount


@dataclass
class NoiseSpec:
    canonical: str
    per_month: float
    lo: float
    hi: float
    templates: list[str]
    weekend_bias: bool = False
    round_to: int = 0  # 0 = paise-level, else round to nearest N


@dataclass
class Profile:
    name: str
    seed: int
    account: str
    card: str
    subs: list[SubSpec]
    decoys: list[DecoySpec]
    noise: list[NoiseSpec]
    redundant_pairs: list[list[str]] = field(default_factory=list)
    # One bank per account, one issuer per card.
    bank_sender: str = "VM-HDFCBK"
    bank_signoff: str = "-HDFC Bank"
    card_sender: str = "VM-ICICIB"
    card_brand: str = "ICICI Bank"
    card_signoff: str = "-ICICI Bank"


# --------------------------------------------------------------------- noise table


def _noise(scale: float = 1.0) -> list[NoiseSpec]:
    """Shared noise catalogue. `scale` bumps volume for the family profile."""
    return [
        NoiseSpec("Swiggy", 6.0 * scale, 150, 700, [
            "UPI/SWIGGY/{ref6}/PAYMENT",
            "POS {card}XXXX1102 SWIGGY BUNDL TECH {city}",
            "UPI/SWIGGYUPI/{ref6}/PAY",
        ], weekend_bias=True),
        NoiseSpec("Zomato", 4.0 * scale, 160, 750, [
            "UPI/ZOMATO/{ref6}/PAYMENT",
            "POS {card}XXXX1102 ZOMATO LTD {city}",
        ], weekend_bias=True),
        NoiseSpec("Amazon retail", 3.5 * scale, 200, 4500, [
            "POS {card}XXXX1102 AMAZON.IN {city}",
            "UPI/AMAZONPAY/{ref6}/PAYMENT",
            "NEFT-AMAZONSELLER-{ref4}-RTGS",
        ]),
        NoiseSpec("Uber", 5.0 * scale, 80, 600, [
            "UPI/UBERINDIA/{ref6}/PAYMENT",
            "POS {card}XXXX1102 UBER INDIA SYSTEMS {city}",
        ]),
        NoiseSpec("Fuel", 2.0 * scale, 500, 3000, [
            "POS {card}XXXX1102 HP PETRO PUMP {city}",
            "POS {card}XXXX1102 INDIAN OIL {city}",
            "UPI/BHARATPETRO/{ref6}/PAYMENT",
        ], round_to=10),
        NoiseSpec("UPI transfer", 5.0 * scale, 100, 2000, [
            "UPI/PRIYA{ref4}@OKAXIS/{ref6}/PAYMENT",
            "UPI/ARJUN{ref4}@OKHDFCBANK/{ref6}/PAYMENT",
            "UPI/MEGHA{ref4}@YBL/{ref6}/PAYMENT",
            "IMPS-P2A-{ref6}-ROHIT SHARMA",
        ], round_to=50),
        NoiseSpec("ATM", 1.5 * scale, 500, 10000, [
            "ATM WDL {city} {ref6}",
            "ATM CASH {ref6} {city}",
        ], round_to=500),
        NoiseSpec("IRCTC", 0.7 * scale, 300, 2500, [
            "UPI/IRCTCUPI/{ref6}/PAYMENT",
            "POS {card}XXXX1102 IRCTC NEW DELHI",
        ]),
    ]


# ------------------------------------------------------------------------ profiles


def _decoys_young() -> list[DecoySpec]:
    return [
        DecoySpec("Rent", "rent", 18000, 3, [
            "NEFT-RAMESH KUMAR-{ref4}-RENT", "IMPS-P2A-{ref6}-RAMESH KUMAR RENT",
        ]),
        DecoySpec("Salary", "salary", 95000, 1, [
            "SALARY ACME TECHNOLOGIES PVT LTD {ref6}",
            "NEFT-ACME TECHNOLOGIES-{ref4}-SALARY",
        ], direction="credit"),
        DecoySpec("Home loan EMI", "emi", 12450, 5, [
            "ACH-D- HDFCLOAN EMI {ref6}", "EMI HDFC LTD {ref6}",
        ]),
        DecoySpec("Consumer EMI", "emi", 4200, 15, [
            "ACH-D- BAJAJFIN EMI {ref6}", "NACH-BAJAJ FINSERV-{ref4}",
        ]),
        DecoySpec("SIP", "sip", 5000, 10, [
            "ACH-D- GROWW NIPPON INDIA MF SIP", "NACH-SIP GROWW-{ref4}-MF",
        ]),
        DecoySpec("Credit card autopay", "cc_bill", 26000, 20, [
            "CC PAYMENT AUTOPAY HDFC {ref4}", "AUTOPAY CARD PAYMENT {ref6}",
        ], varies=0.55),
        DecoySpec("Electricity", "utility", 1900, 12, [
            "BESCOM BILL PAYMENT {ref6}", "UPI/BESCOMBLR/{ref6}/PAYMENT",
        ], varies=0.45),
    ]


def _decoys_student() -> list[DecoySpec]:
    return [
        DecoySpec("Rent", "rent", 8500, 4, [
            "NEFT-SUNITA PG-{ref4}-RENT", "IMPS-P2A-{ref6}-PG HOSTEL RENT",
        ]),
        DecoySpec("Stipend", "salary", 15000, 2, [
            "NEFT-PARENT TRANSFER-{ref4}-MONTHLY",
            "IMPS-P2A-{ref6}-SURESH KALA",
        ], direction="credit"),
        DecoySpec("Phone EMI", "emi", 2499, 6, [
            "ACH-D- BAJAJFIN EMI {ref6}", "NACH-BAJAJ FINSERV-{ref4}",
        ]),
        DecoySpec("Laptop EMI", "emi", 3200, 17, [
            "ACH-D- HDB FINANCIAL EMI {ref6}", "EMI HDBFS {ref6}",
        ]),
        DecoySpec("SIP", "sip", 1000, 9, [
            "ACH-D- ZERODHA COIN SIP", "NACH-SIP ZERODHA-{ref4}-MF",
        ]),
        DecoySpec("Credit card autopay", "cc_bill", 6500, 21, [
            "CC PAYMENT AUTOPAY ICICI {ref4}", "AUTOPAY CARD PAYMENT {ref6}",
        ], varies=0.6),
        DecoySpec("Electricity", "utility", 750, 14, [
            "MSEB BILL PAYMENT {ref6}", "UPI/MAHADISCOM/{ref6}/PAYMENT",
        ], varies=0.4),
    ]


def _decoys_family() -> list[DecoySpec]:
    return [
        DecoySpec("Rent", "rent", 32000, 2, [
            "NEFT-VIJAY MEHTA-{ref4}-RENT", "IMPS-P2A-{ref6}-VIJAY MEHTA RENT",
        ]),
        DecoySpec("Salary", "salary", 185000, 1, [
            "SALARY GLOBEX CONSULTING PVT LTD {ref6}",
            "NEFT-GLOBEX CONSULTING-{ref4}-SALARY",
        ], direction="credit"),
        DecoySpec("Home loan EMI", "emi", 42000, 5, [
            "ACH-D- SBILOAN HOME EMI {ref6}", "EMI SBI HOME LOAN {ref6}",
        ]),
        DecoySpec("Car EMI", "emi", 18500, 16, [
            "ACH-D- ICICILOAN CAR EMI {ref6}", "NACH-ICICI BANK LOAN-{ref4}",
        ]),
        DecoySpec("SIP", "sip", 15000, 8, [
            "ACH-D- KUVERA AXIS BLUECHIP SIP", "NACH-SIP KUVERA-{ref4}-MF",
        ]),
        DecoySpec("Credit card autopay", "cc_bill", 48000, 22, [
            "CC PAYMENT AUTOPAY AXIS {ref4}", "AUTOPAY CARD PAYMENT {ref6}",
        ], varies=0.5),
        DecoySpec("Electricity", "utility", 4200, 13, [
            "TATA POWER BILL {ref6}", "UPI/TATAPOWERDL/{ref6}/PAYMENT",
        ], varies=0.5),
    ]


PROFILES: list[Profile] = [
    Profile(
        name="young_professional", seed=20260725, account="XX4471", card="4471",
        subs=[
            SubSpec("Netflix", "streaming", 649, "monthly", 14, [
                "UPI/NETFLIX BILLDESK/{ref6}/PAYMENT",
                "ACH-D- NETFLIX ENTERTAINMENT SERVICES",
                "NEFT-NETFLIXENT-{ref4}-RTGS",
                "POS {card}XXXX2210 NETFLIX.COM MUMBAI",
            ]),
            SubSpec("Spotify", "music", 119, "monthly", 7, [
                "UPI/SPOTIFYINDIA/{ref6}/PAYMENT",
                "ACH-D- SPOTIFY INDIA LLP",
                "POS {card}XXXX2210 SPOTIFY.COM MUMBAI",
            ], anomaly={"kind": "step", "at": 8, "to": 149.0}),
            SubSpec("JioHotstar", "streaming", 299, "quarterly", 21, [
                "UPI/HOTSTARSUB/{ref6}/PAYMENT",
                "ACH-D- JIOHOTSTAR DIGITAL",
                "POS {card}XXXX2210 HOTSTAR.COM MUMBAI",
            ]),
            SubSpec("Cult.fit", "fitness", 1499, "monthly", 3, [
                "UPI/CULTFIT/{ref6}/PAYMENT",
                "ACH-D- CUREFIT HEALTHCARE PVT LTD",
                "NEFT-CULTFITIND-{ref4}-RTGS",
                "POS {card}XXXX2210 CULT.FIT BENGALURU",
            ], anomaly={"kind": "creep", "at": [4, 9, 14], "pct": 0.08}),
            SubSpec("Adobe CC", "saas", 1675, "monthly", 5, [
                "UPI/ADOBEINDIA/{ref6}/PAYMENT",
                "ACH-D- ADOBE SYSTEMS INDIA PVT LTD",
                "POS {card}XXXX2210 ADOBE.COM NOIDA",
            ], anomaly={"kind": "step", "at": 11, "to": 1950.0}),
            SubSpec("Google One", "cloud", 1300, "annual", 18, [
                "UPI/GOOGLEONE/{ref6}/PAYMENT",
                "ACH-D- GOOGLE INDIA PVT LTD",
                "POS {card}XXXX2210 GOOGLE ONE GURGAON",
            ], anomaly={"kind": "forgotten_annual"}),
            SubSpec("Amazon Prime", "streaming", 1499, "annual", 26, [
                "UPI/AMAZONPRIME/{ref6}/PAYMENT",
                "ACH-D- AMAZON PRIME INDIA",
                "POS {card}XXXX2210 PRIMEVIDEO.COM MUMBAI",
            ]),
            SubSpec("JioSaavn", "music", 99, "monthly", 11, [
                "UPI/JIOSAAVN/{ref6}/PAYMENT",
                "ACH-D- SAAVN MEDIA PVT LTD",
                "POS {card}XXXX2210 JIOSAAVN.COM MUMBAI",
            ]),
            SubSpec("ChatGPT Plus", "saas", 1999, "monthly", 23, [
                "UPI/OPENAI/{ref6}/PAYMENT",
                "POS {card}XXXX2210 OPENAI.COM SAN FRANCISCO",
                "NEFT-OPENAILLC-{ref4}-RTGS",
            ], anomaly={"kind": "trial", "trial_amount": 1.0}),
        ],
        decoys=_decoys_young(), noise=_noise(1.0),
        redundant_pairs=[["Spotify", "JioSaavn"]],
        bank_sender="VM-HDFCBK", bank_signoff="-HDFC Bank",
        card_sender="VM-ICICIB", card_brand="ICICI Bank", card_signoff="-ICICI Bank",
    ),
    Profile(
        name="student", seed=20260726, account="XX8821", card="8821",
        subs=[
            SubSpec("Netflix", "streaming", 199, "monthly", 12, [
                "UPI/NETFLIX BILLDESK/{ref6}/PAYMENT",
                "ACH-D- NETFLIX ENTERTAINMENT SERVICES",
                "POS {card}XXXX3310 NETFLIX.COM MUMBAI",
            ], anomaly={"kind": "step", "at": 10, "to": 249.0}),
            SubSpec("Spotify", "music", 59, "monthly", 5, [
                "UPI/SPOTIFYINDIA/{ref6}/PAYMENT",
                "ACH-D- SPOTIFY INDIA LLP",
                "NEFT-SPOTIFYIN-{ref4}-RTGS",
            ]),
            SubSpec("JioSaavn", "music", 99, "monthly", 19, [
                "UPI/JIOSAAVN/{ref6}/PAYMENT",
                "ACH-D- SAAVN MEDIA PVT LTD",
                "POS {card}XXXX3310 JIOSAAVN.COM MUMBAI",
            ]),
            SubSpec("YouTube Premium", "streaming", 129, "monthly", 8, [
                "UPI/GOOGLEYOUTUBE/{ref6}/PAYMENT",
                "ACH-D- GOOGLE INDIA PVT LTD YT",
                "POS {card}XXXX3310 YOUTUBEPREMIUM GURGAON",
            ], anomaly={"kind": "step", "at": 13, "to": 149.0}),
            SubSpec("ChatGPT Plus", "saas", 1999, "monthly", 22, [
                "UPI/OPENAI/{ref6}/PAYMENT",
                "POS {card}XXXX3310 OPENAI.COM SAN FRANCISCO",
                "NEFT-OPENAILLC-{ref4}-RTGS",
            ], anomaly={"kind": "trial", "trial_amount": 0.0}),
            SubSpec("Canva", "saas", 499, "monthly", 15, [
                "UPI/CANVAPTY/{ref6}/PAYMENT",
                "ACH-D- CANVA PTY LTD",
                "POS {card}XXXX3310 CANVA.COM SYDNEY",
            ], anomaly={"kind": "creep", "at": [4, 9, 14], "pct": 0.08}),
            SubSpec("Google One", "cloud", 1300, "annual", 27, [
                "UPI/GOOGLEONE/{ref6}/PAYMENT",
                "ACH-D- GOOGLE INDIA PVT LTD",
                "POS {card}XXXX3310 GOOGLE ONE GURGAON",
            ], anomaly={"kind": "forgotten_annual"}),
            SubSpec("Jio", "telecom", 299, "monthly", 2, [
                "UPI/JIORECHARGE/{ref6}/PAYMENT",
                "ACH-D- RELIANCE JIO INFOCOMM",
                "POS {card}XXXX3310 JIO.COM MUMBAI",
            ]),
        ],
        decoys=_decoys_student(), noise=_noise(0.75),
        redundant_pairs=[["Spotify", "JioSaavn"], ["Netflix", "YouTube Premium"]],
        bank_sender="JD-AXISBK", bank_signoff="-Axis Bank",
        card_sender="AD-SBIINB", card_brand="SBI", card_signoff="-SBI Card",
    ),
    Profile(
        name="family", seed=20260727, account="XX9207", card="9207",
        subs=[
            SubSpec("Netflix", "streaming", 649, "monthly", 9, [
                "UPI/NETFLIX BILLDESK/{ref6}/PAYMENT",
                "ACH-D- NETFLIX ENTERTAINMENT SERVICES",
                "NEFT-NETFLIXENT-{ref4}-RTGS",
                "POS {card}XXXX7788 NETFLIX.COM MUMBAI",
            ], anomaly={"kind": "step", "at": 9, "to": 799.0}),
            SubSpec("JioHotstar", "streaming", 299, "quarterly", 16, [
                "UPI/HOTSTARSUB/{ref6}/PAYMENT",
                "ACH-D- JIOHOTSTAR DIGITAL",
                "POS {card}XXXX7788 HOTSTAR.COM MUMBAI",
            ]),
            SubSpec("SonyLIV", "streaming", 299, "monthly", 24, [
                "UPI/SONYLIVSUB/{ref6}/PAYMENT",
                "ACH-D- SONY PICTURES NETWORKS INDIA",
                "POS {card}XXXX7788 SONYLIV.COM MUMBAI",
            ]),
            SubSpec("Zee5", "streaming", 199, "monthly", 6, [
                "UPI/ZEE5SUB/{ref6}/PAYMENT",
                "ACH-D- ZEE ENTERTAINMENT ENTERPRISES",
                "POS {card}XXXX7788 ZEE5.COM MUMBAI",
            ]),
            SubSpec("Amazon Prime", "streaming", 1499, "annual", 13, [
                "UPI/AMAZONPRIME/{ref6}/PAYMENT",
                "ACH-D- AMAZON PRIME INDIA",
                "POS {card}XXXX7788 PRIMEVIDEO.COM MUMBAI",
            ], anomaly={"kind": "forgotten_annual"}),
            SubSpec("ACT Fibernet", "telecom", 1349, "monthly", 4, [
                "UPI/ACTFIBERNET/{ref6}/PAYMENT",
                "ACH-D- ATRIA CONVERGENCE TECHNOLOGIES",
                "NEFT-ACTFIBER-{ref4}-RTGS",
            ], anomaly={"kind": "creep", "at": [4, 9, 14], "pct": 0.08}),
            SubSpec("Airtel", "telecom", 999, "monthly", 18, [
                "UPI/AIRTELPOSTPAID/{ref6}/PAYMENT",
                "ACH-D- BHARTI AIRTEL LIMITED",
                "POS {card}XXXX7788 AIRTEL.IN GURGAON",
            ]),
            SubSpec("Cult.fit", "fitness", 2499, "monthly", 11, [
                "UPI/CULTFIT/{ref6}/PAYMENT",
                "ACH-D- CUREFIT HEALTHCARE PVT LTD",
                "POS {card}XXXX7788 CULT.FIT BENGALURU",
            ], anomaly={"kind": "step", "at": 12, "to": 2799.0}),
            SubSpec("Swiggy One", "food", 99, "monthly", 28, [
                "UPI/SWIGGYONE/{ref6}/PAYMENT",
                "ACH-D- BUNDL TECHNOLOGIES PVT LTD",
                "POS {card}XXXX7788 SWIGGY ONE BENGALURU",
            ], anomaly={"kind": "trial", "trial_amount": 1.0}),
        ],
        decoys=_decoys_family(), noise=_noise(1.25),
        redundant_pairs=[["SonyLIV", "Zee5"], ["Netflix", "SonyLIV"]],
        bank_sender="AD-KOTAKB", bank_signoff="-Kotak Bank",
        card_sender="BP-PNBSMS", card_brand="PNB", card_signoff="-PNB",
    ),
]


# ------------------------------------------------------------------------- helpers


def _fill(tpl: str, rng: random.Random, card: str) -> str:
    return (
        tpl.replace("{ref6}", str(rng.randint(100000, 999999)))
        .replace("{ref4}", str(rng.randint(1000, 9999)))
        .replace("{card}", card)
        .replace("{city}", rng.choice(CITIES))
    )


def _anchored(month_index: int, anchor_day: int, rng: random.Random) -> date:
    """Anchor day of month N, with the weekend drift §8's anchoring signal recovers."""
    m = START_DATE + relativedelta(months=month_index)
    day = min(anchor_day, calendar.monthrange(m.year, m.month)[1])
    d = date(m.year, m.month, day) + timedelta(
        days=rng.choice([-2, -1, 0, 0, 0, 0, 1, 2])
    )
    return min(max(d, START_DATE), END_DATE)


def _period_months(period: str) -> int:
    return {"monthly": 1, "quarterly": 3, "annual": 12}[period]


def _txn(d: date, raw: str, amt: float, direction: str, profile: Profile, idx: int) -> dict:
    return {
        "date": d.isoformat(),
        "merchant_raw": raw,
        "amount": round(amt, 2),
        "direction": direction,
        "source": "demo",
        "source_ref": f"demo:{profile.name}:{idx}",
        "account_hint": profile.account,
    }


# ---------------------------------------------------------------------- generation


def _gen_subscriptions(p: Profile, rng: random.Random, counter) -> tuple[list, dict, dict]:
    txns, gt_subs, gt_changes, gt_trials, gt_annual = [], [], [], [], []
    sub_names: dict[str, tuple[str, str]] = {}  # raw string -> (canonical, category)

    for spec in p.subs:
        step = _period_months(spec.period)
        idxs = list(range(0, MONTHS, step))
        if spec.period == "annual":
            idxs = [i for i in idxs if i <= MONTHS - 6]  # 0 and 12 within the window
        dates = [_anchored(i, spec.anchor_day, rng) for i in idxs]
        n = len(dates)

        amounts = [float(spec.amount)] * n
        a = spec.anomaly
        if a and a["kind"] == "step":
            k = min(a["at"], n - 1)
            for i in range(k, n):
                amounts[i] = float(a["to"])
            gt_changes.append({
                "canonical": spec.canonical, "kind": "step",
                "from_amount": float(spec.amount), "to_amount": float(a["to"]),
                "changed_on": dates[k].isoformat(),
                "pct": round((a["to"] - spec.amount) / spec.amount * 100, 2),
            })
        elif a and a["kind"] == "creep":
            cur = float(spec.amount)
            for k in a["at"]:
                if k >= n:
                    continue
                prev, cur = cur, round(cur * (1 + a["pct"]), 2)
                for i in range(k, n):
                    amounts[i] = cur
                gt_changes.append({
                    "canonical": spec.canonical, "kind": "creep",
                    "from_amount": prev, "to_amount": cur,
                    "changed_on": dates[k].isoformat(),
                    "pct": round((cur - prev) / prev * 100, 2),
                })
        elif a and a["kind"] == "trial":
            amounts[0] = float(a["trial_amount"])
            gt_trials.append({
                "canonical": spec.canonical,
                "trial_amount": float(a["trial_amount"]),
                "full_amount": float(spec.amount),
                "converted_on": dates[1].isoformat(),
            })
        elif a and a["kind"] == "forgotten_annual":
            gt_annual.append(spec.canonical)

        used: list[str] = []
        for i, (d, amt) in enumerate(zip(dates, amounts)):
            tpl = spec.templates[i % len(spec.templates)]
            if tpl not in used:
                used.append(tpl)
            raw = _fill(tpl, rng, p.card)
            sub_names[raw] = (spec.canonical, spec.category)
            txns.append(_txn(d, raw, amt, "debit", p, next(counter)))

        periods_per_year = 12 / step
        gt_subs.append({
            "canonical": spec.canonical,
            "category": spec.category,
            "period": spec.period,
            "occurrences": n,
            "current_amount": amounts[-1],
            "annual_cost": round(amounts[-1] * periods_per_year, 2),
            # Only the templates that actually rendered. An annual sub charges twice in
            # 18 months, so it can never exhibit more than 2 variants — ground truth
            # must not claim a string the normalizer will never be shown.
            "raw_variants": used,
            # 18 months cannot contain 3 annual charges — §8's >=3 gate must relax here
            # or every annual subscription is silently dropped.
            "min_occurrences_required": 2 if spec.period == "annual" else 3,
        })

    return txns, {
        "subscriptions": gt_subs,
        "price_changes": gt_changes,
        "trial_conversions": gt_trials,
        "forgotten_annual": gt_annual,
    }, sub_names


def _gen_decoys(p: Profile, rng: random.Random, counter) -> tuple[list, list]:
    txns, gt = [], []
    for spec in p.decoys:
        dates = [_anchored(i, spec.anchor_day, rng) for i in range(MONTHS)]
        for i, d in enumerate(dates):
            amt = spec.amount
            if spec.varies:
                amt = spec.amount * (1 + rng.uniform(-spec.varies, spec.varies))
            raw = _fill(spec.templates[i % len(spec.templates)], rng, p.card)
            txns.append(_txn(d, raw, amt, spec.direction, p, next(counter)))
        gt.append({
            "canonical": spec.canonical, "reason": spec.reason,
            "occurrences": len(dates), "raw_variants": spec.templates,
            "direction": spec.direction, "variable_amount": spec.varies > 0,
        })
    return txns, gt


def _gen_noise(p: Profile, rng: random.Random, counter, needed: int) -> tuple[list, list]:
    """Per-category distributions, weekend-weighted. Fills exactly to `needed`."""
    weights = [n.per_month for n in p.noise]
    txns = []
    for _ in range(needed):
        spec = rng.choices(p.noise, weights=weights, k=1)[0]
        month = rng.randrange(MONTHS)
        m = START_DATE + relativedelta(months=month)
        last = calendar.monthrange(m.year, m.month)[1]
        for _attempt in range(8):
            d = date(m.year, m.month, rng.randint(1, last))
            if not spec.weekend_bias or d.weekday() >= 4 or rng.random() < 0.45:
                break
        d = min(max(d, START_DATE), END_DATE)

        # lognormal-ish: most spends near the low end, a long tail toward hi
        frac = min(1.0, abs(rng.lognormvariate(-1.0, 0.75)))
        amt = spec.lo + frac * (spec.hi - spec.lo)
        if spec.round_to:
            amt = max(spec.round_to, round(amt / spec.round_to) * spec.round_to)

        raw = _fill(rng.choice(spec.templates), rng, p.card)
        txns.append(_txn(d, raw, amt, "debit", p, next(counter)))

    return txns, sorted({n.canonical for n in p.noise})


# ------------------------------------------------------------------ sms + email


def _fmt_amt(amt: float, commas: bool) -> str:
    """Indian lakh/crore grouping: 1,84,325.00 — not 184,325.00."""
    s = f"{amt:.2f}"
    if not commas:
        return s
    ip, _, dp = s.partition(".")
    if len(ip) > 3:
        head, tail = ip[:-3], ip[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        ip = ",".join(groups + [tail])
    return f"{ip}.{dp}"


def _render_sms(txn: dict, p: Profile, rng: random.Random) -> tuple[str, str]:
    """(sender, body). Every body must match a pattern in sms_patterns.SMS_PATTERNS.

    One bank per account, one issuer per card — a real person is not banking with
    five institutions at once. The body format still varies by transaction type,
    which is how banks genuinely template their alerts.
    """
    raw, amt = txn["merchant_raw"], txn["amount"]
    d = date.fromisoformat(txn["date"])
    dmy = d.strftime("%d-%m-%y")
    dmy_slash = d.strftime("%d/%m/%y")
    d_mon = d.strftime("%d-%b-%y")
    dmy_full = d.strftime("%d-%m-%Y")

    bank, card_bank = p.bank_sender, p.card_sender
    sign = p.bank_signoff

    if txn["direction"] == "credit":
        return bank, (
            f"Rs.{_fmt_amt(amt, True)} credited to a/c {p.account} on {dmy} "
            f"by {raw}. Avl Bal INR {_fmt_amt(amt * 3.2, True)}."
        )
    if raw.startswith("ATM"):
        return bank, (
            f"Rs.{_fmt_amt(amt, False)} withdrawn from {raw} a/c {p.account} "
            f"on {dmy}. {sign}"
        )
    if raw.startswith("UPI/"):
        return bank, (
            f"Rs {_fmt_amt(amt, False)} debited from A/c {p.account} {raw} "
            f"on {dmy}. Not you? SMS BLOCK to 9951860002"
        )
    if raw.startswith(("ACH", "NACH", "ECS")):
        return bank, (
            f"Rs.{_fmt_amt(amt, True)} debited towards {raw} on {dmy_slash}. {sign}"
        )
    if raw.startswith("POS"):
        return card_bank, (
            f"INR {_fmt_amt(amt, True)} spent on {p.card_brand} Card XX{p.card} "
            f"at {raw} on {d_mon}. Avl Lmt: INR {_fmt_amt(184325, True)}"
        )
    if raw.startswith(("NEFT", "IMPS")):
        return bank, (
            f"Rs.{_fmt_amt(amt, True)} debited from a/c {p.account} on {dmy} "
            f"to {raw} via NetBanking. Not you? Call 18002586161"
        )
    if rng.random() < 0.5:
        # Quotes the account, so it comes from the bank — not the card issuer.
        return bank, (
            f"Rs.{_fmt_amt(amt, False)} spent via {p.account} at {raw} "
            f"on {dmy_full}. {sign}"
        )
    return bank, (
        f"Rs.{_fmt_amt(amt, True)} has been debited for {raw} on {dmy} "
        f"from {p.account}. {sign}"
    )


NON_BANK = [
    ("VM-AMAZON", "Your OTP for Amazon login is {otp}. Do not share it with anyone."),
    ("AD-SWIGGY", "Your order from Punjabi Rasoi has been delivered. Rate your experience!"),
    ("JD-ZOMATO", "FLAT 60% OFF on your next 3 orders. Use code ZOMATO60. T&C apply."),
    ("VK-OLACAB", "Your Ola ride is arriving in 3 mins. Driver: Ramesh, KA01AB{r4}"),
    ("AX-IRCTC", "PNR {r6} CNF. Train 12628 departs 06:15. Happy journey!"),
    ("TX-JIOTEL", "Recharge successful. Enjoy 2GB/day for 28 days. Balance: unlimited"),
    ("VM-BIGBSK", "MEGA SALE! Upto 45% off on groceries. Shop now at bigbasket.com"),
    ("AD-MYNTRA", "END OF REASON SALE is LIVE. 50-80% off on 5000+ brands."),
    ("VM-APOLLO", "Your medicines have been dispatched. Track: apollo.in/t/{r6}"),
    ("JD-URBANC", "Your Urban Company booking is confirmed for tomorrow 11:00 AM."),
    ("AD-GOOGLE", "G-{otp} is your Google verification code."),
    ("VM-WHATSA", "Your WhatsApp code: {otp}. Don't share this code."),
    ("TX-PAYTM1", "Cashback of Rs 25 credited to your Paytm wallet. Shop more, save more!"),
    ("VK-DUNZO1", "Your Dunzo order is out for delivery. ETA 12 mins."),
    ("AD-CRED01", "You have 4,280 CRED coins expiring soon. Redeem now."),
]


def _render_non_bank(rng: random.Random) -> str:
    sender, tpl = rng.choice(NON_BANK)
    body = (
        tpl.replace("{otp}", str(rng.randint(100000, 999999)))
        .replace("{r6}", str(rng.randint(100000, 999999)))
        .replace("{r4}", str(rng.randint(1000, 9999)))
    )
    return f"{sender}: {body}"


EMAIL_SENDERS = {
    "streaming": "billing@razorpay.com", "music": "receipts@razorpay.com",
    "saas": "invoice@razorpay.com", "cloud": "payments@google.com",
    "fitness": "billing@cure.fit", "telecom": "bills@paytm.com",
    "food": "noreply@razorpay.com",
}


def _render_emails(txns: list[dict], sub_names: dict, rng: random.Random) -> list[dict]:
    """Subscriptions emit an email receipt as well as an SMS — this is what §6.7 dedups."""
    out = []
    for t in txns:
        name = sub_names.get(t["merchant_raw"])
        if not name:
            continue
        canonical, category = name
        d = date.fromisoformat(t["date"])
        out.append({
            "id": f"msg_{len(out):05d}",
            "from": EMAIL_SENDERS.get(category, "noreply@razorpay.com"),
            "subject": rng.choice([
                f"Payment successful - {canonical}",
                f"Your {canonical} receipt",
                f"{canonical} subscription renewed",
                f"Invoice for {canonical}",
            ]),
            "date": t["date"],
            "body_text": (
                f"Hello,\n\nWe have received your payment of Rs {t['amount']:,.2f} "
                f"for {canonical} on {d.strftime('%d %B %Y')}.\n\n"
                f"Reference: {t['merchant_raw']}\n"
                f"Amount: INR {t['amount']:,.2f}\n"
                f"Date: {d.strftime('%d %B %Y')}\n\n"
                f"This is an automated receipt. Do not reply.\n"
            ),
        })
    return out


# ----------------------------------------------------------------------- assemble


def generate(p: Profile) -> dict:
    rng = random.Random(p.seed)
    counter = iter(range(100000))

    sub_txns, gt_sub, sub_names = _gen_subscriptions(p, rng, counter)
    decoy_txns, gt_excluded = _gen_decoys(p, rng, counter)
    noise_needed = max(400, TARGET_TXNS - len(sub_txns) - len(decoy_txns))
    noise_txns, noise_merchants = _gen_noise(p, rng, counter, noise_needed)

    txns = sorted(sub_txns + decoy_txns + noise_txns, key=lambda t: (t["date"], t["source_ref"]))

    sms_lines = []
    for t in txns:
        sender, body = _render_sms(t, p, rng)
        sms_lines.append(f"{sender}: {body}")
    bank_count = len(sms_lines)
    for _ in range(int(bank_count * 2.5)):
        sms_lines.append(_render_non_bank(rng))
    rng.shuffle(sms_lines)

    emails = _render_emails(txns, sub_names, rng)

    ground_truth = {
        "profile": p.name,
        "seed": p.seed,
        "window": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat(), "months": MONTHS},
        "transaction_count": len(txns),
        **gt_sub,
        "redundant_pairs": p.redundant_pairs,
        "excluded": gt_excluded,
        "noise_merchants": noise_merchants,
        "noise_count": len(noise_txns),
        "expected_dedup_pairs": len(emails),
        "sms_line_count": len(sms_lines),
        "sms_bank_line_count": bank_count,
    }
    return {"transactions": txns, "ground_truth": ground_truth,
            "sms": sms_lines, "emails": emails}


def write(p: Profile, bundle: dict) -> None:
    d = OUT_DIR / p.name
    d.mkdir(parents=True, exist_ok=True)
    (d / "transactions.json").write_text(
        json.dumps(bundle["transactions"], indent=2) + "\n", encoding="utf-8")
    (d / "ground_truth.json").write_text(
        json.dumps(bundle["ground_truth"], indent=2) + "\n", encoding="utf-8")
    (d / "sms.txt").write_text("\n".join(bundle["sms"]) + "\n", encoding="utf-8")
    (d / "emails.json").write_text(
        json.dumps(bundle["emails"], indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for p in PROFILES:
        b = generate(p)
        write(p, b)
        gt = b["ground_truth"]
        print(
            f"{p.name:20s} {gt['transaction_count']:4d} txns · "
            f"{len(gt['subscriptions'])} subs · {gt['noise_count']} noise · "
            f"{len(gt['excluded'])} excluded · {len(gt['price_changes'])} price changes · "
            f"{gt['sms_line_count']} sms lines ({gt['sms_bank_line_count']} bank) · "
            f"{len(b['emails'])} emails"
        )


if __name__ == "__main__":
    main()
