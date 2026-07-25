"""Sieve API.

Stateless by construction: transactions arrive in the request body, the analysis
comes back, nothing is written anywhere. That is stronger than §16's
"session-scoped, in-memory" promise — there is no session either, so there is
nothing to leak, expire, or delete.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import actions
import dormancy
import exclusions
import normalize
import scoring
from adapters import (
    DEMO_PROFILES, CsvAdapter, DemoAdapter, SmsPasteAdapter, SmsXmlAdapter,
)
from models import Transaction
from price_change import detect_price_changes
from recurrence import PERIODS_PER_YEAR, detect_recurrence

MAX_TRANSACTIONS = 20_000

app = FastAPI(title="Sieve API")

# ponytail: wildcard CORS. There is no auth and no cookie, so this grants
# nothing. Pin to the Vercel origin the moment a session cookie exists.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------- contracts


class TransactionIn(BaseModel):
    date: date
    merchant_raw: str = Field(min_length=1, max_length=500)
    amount: float = Field(ge=0)
    direction: Literal["debit", "credit"]
    source: Literal["demo", "sms_paste", "sms_xml", "gmail", "csv"]
    source_ref: Optional[str] = None
    account_hint: Optional[str] = None


class AnalyzeRequest(BaseModel):
    # Bounded on purpose: this is a trust boundary and the whole analysis runs
    # in memory. 20k covers a 5,000-message SMS export several times over.
    transactions: list[TransactionIn] = Field(min_length=1, max_length=MAX_TRANSACTIONS)
    usage_taps: dict[str, Literal["yes", "no", "unsure"]] = Field(default_factory=dict)


# -------------------------------------------------------------------- pipeline


def analyze(txns: list[Transaction], usage_taps: dict[str, str] | None = None) -> dict:
    """normalize -> exclude -> recur -> price -> dormancy -> score -> act."""
    taps = usage_taps or {}
    clusters = normalize.cluster(txns, use_llm=False)
    kept, excluded = exclusions.split(clusters)

    # Pass 1 — which clusters are actually subscriptions.
    found = []
    for c in kept:
        rec = detect_recurrence(c.transactions)
        if rec is None:
            continue
        changes = detect_price_changes(c.transactions, PERIODS_PER_YEAR[rec.period])
        found.append((c, rec, changes))

    # Pass 2 — scoring needs the whole set: redundancy peers and the priciest sub.
    redundant = dormancy.redundancy_map([c for c, _, _ in found])
    max_annual = max((r.annual_cost for _, r, _ in found), default=0.0)

    subscriptions = []
    for cluster, rec, changes in found:
        peers = redundant.get(cluster.canonical, [])
        dorm_score, signals = dormancy.assess(
            cluster, rec.period, changes, clusters, peers,
            taps.get(cluster.canonical),
        )
        tier = actions.cheaper_tier(cluster.canonical, rec.current_amount)
        score, breakdown = scoring.leak_score(
            annual_cost=rec.annual_cost,
            max_annual_cost=max_annual,
            dormancy=dorm_score,
            is_redundant=bool(peers),
            has_unnoticed_hike=bool(changes),
            has_cheaper_tier=tier is not None,
        )
        band = scoring.band(score)
        action = actions.decide(
            cluster, band, rec.current_amount, rec.annual_cost,
            PERIODS_PER_YEAR[rec.period], changes,
        )

        subscriptions.append({
            "canonical": cluster.canonical,
            "category": cluster.category,
            "period": rec.period,
            "period_days": rec.period_days,
            "confidence": rec.confidence,
            "current_amount": rec.current_amount,
            "annual_cost": rec.annual_cost,
            "next_charge_date": rec.next_charge_date,
            "occurrences": rec.occurrences,
            "leak_score": score,
            "band": band,
            "score_breakdown": breakdown,
            "why_this_score": scoring.explain(breakdown),
            "dormancy_signals": signals,
            "redundant_with": peers,
            "cheaper_tier": {"name": tier[0], "price": tier[1]} if tier else None,
            "raw_variants": cluster.raw_variants,
            "price_changes": [
                {"from_amount": c.from_amount, "to_amount": c.to_amount,
                 "changed_on": c.changed_on, "pct": c.pct,
                 "annual_impact": c.annual_impact, "kind": c.kind}
                for c in changes
            ],
            # Compact enough for the row's sparkline; this merchant only.
            "price_history": [
                {"date": t.date, "amount": t.amount} for t in cluster.transactions
            ],
            "action": {
                "kind": action.kind, "label": action.label, "url": action.url,
                "menu_path": action.menu_path,
                "est_annual_saving": action.est_annual_saving,
            },
        })

    subscriptions.sort(key=lambda s: s["leak_score"], reverse=True)
    monthly_leak = sum(s["annual_cost"] for s in subscriptions) / 12
    savings = sum(s["action"]["est_annual_saving"] for s in subscriptions)
    excluded_groups = _group_excluded(excluded)

    return {
        "subscriptions": subscriptions,
        "excluded": excluded_groups,
        "portfolio": {
            "monthly_leak": round(monthly_leak, 2),
            "annual_leak": round(monthly_leak * 12, 2),
            "annual_savings_if_actioned": round(savings, 2),
            "portfolio_leak_score": scoring.portfolio_score(
                [(s["leak_score"], s["annual_cost"]) for s in subscriptions]),
            "subscription_count": len(subscriptions),
            # The headline claim is "N recurring payments correctly excluded",
            # so this counts CLASSES to match the panel — not raw clusters.
            "excluded_count": len(excluded_groups),
            "excluded_transactions": sum(len(e.cluster.transactions) for e in excluded),
            "transactions_analyzed": len(txns),
        },
    }


EXCLUSION_LABELS = {
    "rent": "Rent", "salary": "Salary / income", "emi": "EMI / loan repayment",
    "sip": "SIP / investment", "cc_bill": "Credit card bill",
    "utility": "Utilities",
}


def _group_excluded(excluded) -> list[dict]:
    """One row per exclusion CLASS, not per raw string.

    §8.1's panel is the claim "6 recurring payments correctly excluded". Listing
    per-cluster shows the same obligation twice whenever its two bank templates
    clean to strings too different to fuzzy-merge (SUNITA PG RENT vs P2A PG
    HOSTEL RENT), which inflates the count on the one panel whose entire value
    is being right.
    """
    groups: dict[str, dict] = {}
    for e in excluded:
        monthly = sum(t.amount for t in e.cluster.transactions) / 18.0
        g = groups.setdefault(e.reason, {
            "reason": e.reason,
            "label": EXCLUSION_LABELS.get(e.reason, e.reason),
            "occurrences": 0, "approx_monthly": 0.0, "merchants": [],
        })
        g["occurrences"] += len(e.cluster.transactions)
        g["approx_monthly"] += monthly
        g["merchants"].append({
            "canonical": e.cluster.canonical, "detail": e.detail,
            "occurrences": len(e.cluster.transactions),
            "raw_variants": e.cluster.raw_variants,
        })
    for g in groups.values():
        g["approx_monthly"] = round(g["approx_monthly"], 2)
    return sorted(groups.values(), key=lambda g: -g["approx_monthly"])


# ------------------------------------------------------------------- endpoints


@app.get("/health")
def health():
    return {"status": "ok", "service": "sieve"}


@app.post("/analyze")
def analyze_endpoint(req: AnalyzeRequest):
    txns = [Transaction(**t.model_dump()) for t in req.transactions]
    return analyze(txns, req.usage_taps)


MAX_UPLOAD = 40 * 1024 * 1024


class PasteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8_000_000)


def _ingest(result) -> dict:
    """Every ingestion path returns the same shape as /demo/{profile}, so the
    frontend renders all of them through one code path."""
    if not result.transactions:
        raise HTTPException(
            422,
            "No transactions found. " + (result.receipt.summary() or "Nothing readable."),
        )
    return {
        "receipt": {**vars(result.receipt), "summary": result.receipt.summary()},
        **analyze(result.transactions),
    }


@app.post("/ingest/sms")
def ingest_sms(req: PasteRequest):
    """§6.3 — the hero feature. Paste, no permissions, fifteen seconds."""
    return _ingest(SmsPasteAdapter().fetch(req.text))


@app.post("/ingest/sms-xml")
async def ingest_sms_xml(request: Request):
    """§6.4 — SMS Backup & Restore export. Raw body, not multipart: it avoids a
    dependency and the browser can POST a File object directly."""
    raw = await request.body()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, f"file exceeds {MAX_UPLOAD // 1024 // 1024}MB")
    try:
        return _ingest(SmsXmlAdapter().fetch(raw))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/ingest/csv")
async def ingest_csv(request: Request):
    """§6.6 — statement export."""
    raw = await request.body()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, f"file exceeds {MAX_UPLOAD // 1024 // 1024}MB")
    try:
        return _ingest(CsvAdapter().fetch(raw))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class RenegotiateRequest(BaseModel):
    canonical: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=40)
    current_amount: float = Field(gt=0)
    original_amount: float = Field(gt=0)
    period: Literal["weekly", "monthly", "quarterly", "annual"] = "monthly"


@app.post("/renegotiate")
def renegotiate(req: RenegotiateRequest):
    """Drafted on demand, not during /analyze.

    Keeps the judge's /demo path fast and free of any network call the LLM could
    stall. Falls back to a static template if Groq is unreachable, so this
    endpoint has no failure mode that returns nothing.
    """
    draft = actions.renegotiation_email(
        req.canonical, req.category, req.current_amount,
        req.original_amount, req.period,
    )
    return {"canonical": req.canonical, "draft": draft}


@app.get("/demo")
def demo_profiles():
    return {"profiles": list(DEMO_PROFILES)}


@app.get("/demo/{profile}")
def demo(profile: str):
    """The judge's path: no auth, no upload, no network beyond this call."""
    if profile not in DEMO_PROFILES:
        raise HTTPException(404, f"unknown profile; try one of {DEMO_PROFILES}")
    result = DemoAdapter().fetch(profile)
    return {
        "profile": profile,
        "receipt": {**vars(result.receipt), "summary": result.receipt.summary()},
        **analyze(result.transactions),
    }
