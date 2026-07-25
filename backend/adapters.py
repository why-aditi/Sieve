"""Ingestion adapters — spec §6.

Two implementations, one interface. Nothing downstream knows or cares which
ran: both emit `Transaction[]` built from the same frozen §5 dataclass.

    DemoAdapter   bundled profiles, zero network (§6.2)
    CsvAdapter    date / description / amount, fuzzy column matching (§6.6)

One addition to §6.1's `fetch(payload) -> list[Transaction]` sketch: fetch
returns a `FetchResult` carrying the transactions AND a `ScanReceipt`. §15
requires the "what we read" receipt, and a bare list cannot carry those counts.
The transactions field is still plain `list[Transaction]`, so downstream is
unchanged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from rapidfuzz import fuzz

from models import Transaction

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEMO_PROFILES = ("student", "young_professional", "family")

MAX_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_CSV_ROWS = 50_000


@dataclass
class ScanReceipt:
    """The §15 honesty receipt. Every field is a count we actually measured."""
    source: str
    scanned: int = 0        # raw rows we looked at
    matched: int = 0        # became a Transaction
    ignored: int = 0        # not a transaction at all
    unparsed: int = 0       # looked like one, but was unreadable
    attachments_opened: int = 0   # always 0 — we never open them
    bytes_stored: int = 0         # always 0 — there is no database (§16)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"Scanned {self.scanned:,}"]
        if self.ignored:
            parts.append(f"{self.ignored:,} ignored")
        parts.append(f"{self.matched:,} transactions found")
        if self.unparsed:
            parts.append(f"{self.unparsed:,} unreadable")
        parts += ["0 attachments opened", "0 bytes stored"]
        return " · ".join(parts)


@dataclass
class FetchResult:
    transactions: list[Transaction]
    receipt: ScanReceipt


class IngestionAdapter(Protocol):
    source_name: str

    def fetch(self, payload) -> FetchResult: ...


def parse_date(raw: str):
    """Indian statement dates: 14-03-26, 14/03/2026, 05-Apr-26, 2026-03-14.

    dayfirst=True is not optional — '05-04-26' is 5 April in every Indian bank
    export and 4 May to a US-default parser.
    """
    from dateutil import parser as _parser

    try:
        parsed = _parser.parse(raw, dayfirst=True, yearfirst=False).date()
    except (ValueError, OverflowError, TypeError):
        return None
    if not date(2000, 1, 1) <= parsed <= date(2100, 1, 1):
        return None
    return parsed


# --------------------------------------------------------------- DemoAdapter


class DemoAdapter:
    """§6.2 — the judge's path. One click, no network, no auth, cannot fail.

    Reads a bundled profile from /data. The only input is a profile name,
    validated against a fixed tuple, so there is no user-supplied path and
    nothing to traverse.
    """

    source_name = "demo"

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir

    def profiles(self) -> tuple[str, ...]:
        return DEMO_PROFILES

    def fetch(self, payload: str = "young_professional") -> FetchResult:
        if payload not in DEMO_PROFILES:
            raise ValueError(
                f"unknown demo profile {payload!r}; expected one of {DEMO_PROFILES}")

        path = self.data_dir / payload / "transactions.json"
        records = json.loads(path.read_text(encoding="utf-8"))

        txns = [
            Transaction(**{**r, "date": date.fromisoformat(r["date"])})
            for r in records
        ]
        receipt = ScanReceipt(
            source=self.source_name,
            scanned=len(records),
            matched=len(txns),
            notes=[
                f"Bundled demo profile '{payload}' — 18 months of synthetic data",
                "No network call, no credentials, no upload",
            ],
        )
        return FetchResult(transactions=txns, receipt=receipt)


# ---------------------------------------------------------------- CsvAdapter

# Real Indian bank exports, not a tidy spec. HDFC ships "Withdrawal Amt." and
# "Deposit Amt." as separate columns; ICICI ships "Transaction Remarks"; SBI
# ships "Txn Date". Matching is fuzzy so near-misses still land.
COLUMN_SYNONYMS = {
    "date": ["date", "txn date", "transaction date", "value date", "tran date",
             "posting date"],
    "description": ["description", "narration", "particulars", "remarks",
                    "transaction remarks", "details", "merchant", "payee"],
    "amount": ["amount", "txn amount", "transaction amount", "amount (inr)"],
    "type": ["type", "dr/cr", "drcr", "cr/dr", "transaction type", "debit/credit"],
    "debit": ["withdrawal amt", "withdrawal amount", "debit", "debit amount",
              "withdrawal", "dr"],
    "credit": ["deposit amt", "deposit amount", "credit", "credit amount",
               "deposit", "cr"],
}
COLUMN_MATCH_RATIO = 82


def _match_columns(headers: list[str]) -> dict[str, str]:
    """Fuzzy-map real headers onto the roles we need."""
    normed = {h: re.sub(r"[^a-z0-9 ]", "", str(h).strip().lower()) for h in headers}
    found: dict[str, str] = {}
    for role, options in COLUMN_SYNONYMS.items():
        best, best_score = None, 0.0
        for header, norm in normed.items():
            if not norm:
                continue
            score = max(fuzz.ratio(norm, opt) for opt in options)
            if score > best_score:
                best, best_score = header, score
        if best is not None and best_score >= COLUMN_MATCH_RATIO:
            found[role] = best
    return found


class CsvAdapter:
    """§6.6 — a statement exported from net banking."""

    source_name = "csv"

    def fetch(self, payload: bytes | str) -> FetchResult:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError(
                f"file is {len(raw) / 1e6:.0f}MB; the limit is "
                f"{MAX_UPLOAD_BYTES / 1e6:.0f}MB")

        import io

        import pandas as pd

        try:
            frame = pd.read_csv(
                io.BytesIO(raw), nrows=MAX_CSV_ROWS, dtype=str,
                skipinitialspace=True, encoding_errors="replace",
            )
        except Exception:
            raise ValueError(
                "That file isn't a readable CSV. Export your statement as CSV "
                "from net banking and try again."
            ) from None

        frame.columns = [str(c).strip() for c in frame.columns]
        cols = _match_columns(list(frame.columns))

        missing = [r for r in ("date", "description") if r not in cols]
        has_amount = "amount" in cols or "debit" in cols or "credit" in cols
        if missing or not has_amount:
            seen = [c[:24] for c in frame.columns[:6] if c and not c.startswith("Unnamed")]
            raise ValueError(
                "Couldn't find the columns Sieve needs — a date, a description "
                "and an amount. The columns in this file are: "
                + (", ".join(seen) if seen else "(none readable)")
            )

        receipt = ScanReceipt(source=self.source_name)
        txns: list[Transaction] = []

        for index, row in frame.iterrows():
            receipt.scanned += 1
            parsed = self._row(row, cols, int(index))
            if parsed is None:
                receipt.unparsed += 1
                continue
            txns.append(parsed)

        receipt.matched = len(txns)
        receipt.notes.append(
            "Matched columns: "
            + ", ".join(f"{role} -> {col!r}" for role, col in sorted(cols.items()))
        )
        if receipt.unparsed:
            receipt.notes.append(
                f"{receipt.unparsed} row(s) had no readable date or amount")
        return FetchResult(transactions=txns, receipt=receipt)

    def _row(self, row, cols: dict[str, str], index: int) -> Transaction | None:
        when = parse_date(str(row.get(cols["date"]) or "").strip())
        merchant = str(row.get(cols["description"]) or "").strip()
        if when is None or not merchant:
            return None

        amount, direction = self._amount(row, cols)
        if amount is None:
            return None

        return Transaction(
            date=when,
            merchant_raw=merchant,
            amount=round(amount, 2),
            direction=direction,
            source="csv",
            source_ref=f"csv:{index}",
            account_hint=None,
        )

    @staticmethod
    def _amount(row, cols: dict[str, str]) -> tuple[float | None, str]:
        def num(value) -> float | None:
            text = re.sub(r"[^\d.\-]", "", str(value or ""))
            try:
                return abs(float(text)) if text not in ("", "-", ".") else None
            except ValueError:
                return None

        # Shape A: separate withdrawal / deposit columns. Direction is implied
        # by which one is populated — no type column needed.
        if "debit" in cols or "credit" in cols:
            debit = num(row.get(cols.get("debit"))) if "debit" in cols else None
            credit = num(row.get(cols.get("credit"))) if "credit" in cols else None
            # `is not None`, not truthiness: a Rs 0.00 free-trial charge is a
            # real row, and `if debit:` silently deletes it.
            if debit is not None:
                return debit, "debit"
            if credit is not None:
                return credit, "credit"
            return None, "debit"

        # Shape B: one amount column plus a Dr/Cr marker.
        amount = num(row.get(cols["amount"]))
        if amount is None:
            return None, "debit"
        marker = str(row.get(cols.get("type")) or "").strip().lower()
        credit_like = marker.startswith(("c", "cr", "credit", "deposit"))
        return amount, "credit" if credit_like else "debit"
