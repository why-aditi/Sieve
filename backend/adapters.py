"""Ingestion adapters — spec §6.

Five implementations, one interface. Nothing downstream knows or cares which
ran: they all emit `Transaction[]` built from the same frozen §5 dataclass.

    DemoAdapter      bundled profiles, zero network        <- built
    SmsPasteAdapter  pasted bank SMS                       <- next
    SmsXmlAdapter    SMS Backup & Restore export
    CsvAdapter       date/description/amount/type
    GmailAdapter     gated on the frontend (§18 hour 13)

One addition to §6.1's `fetch(payload) -> list[Transaction]` sketch: fetch
returns a `FetchResult` carrying the transactions AND a `ScanReceipt`. §15
requires the "what we read" receipt — *"Scanned 4,182 messages · 340 from bank
senders · 3,842 ignored · 0 attachments opened · 0 bytes stored"* — and a bare
list cannot carry those counts. The transactions field is still plain
`list[Transaction]`, so downstream is unchanged.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from config import GROQ_MODEL, groq_key
from models import Transaction
from sms_patterns import is_bank_sender, looks_financial, parse_body, parse_date

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEMO_PROFILES = ("student", "young_professional", "family")


@dataclass
class ScanReceipt:
    """The §15 honesty receipt. Every field is a count we actually measured."""
    source: str
    scanned: int = 0        # raw records we looked at
    matched: int = 0        # became a Transaction
    ignored: int = 0        # not a bank record at all
    unparsed: int = 0       # looked like one, but no pattern matched
    llm_recovered: int = 0  # rescued by the batched LLM fallback
    attachments_opened: int = 0   # always 0 — we never open them (§6.5)
    bytes_stored: int = 0         # always 0 — there is no database (§16)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"Scanned {self.scanned:,}"]
        if self.ignored:
            parts.append(f"{self.ignored:,} ignored")
        parts.append(f"{self.matched:,} transactions found")
        if self.unparsed:
            parts.append(f"{self.unparsed:,} unreadable")
        if self.llm_recovered:
            parts.append(f"{self.llm_recovered:,} recovered by AI")
        parts += ["0 attachments opened", "0 bytes stored"]
        return " · ".join(parts)


@dataclass
class FetchResult:
    transactions: list[Transaction]
    receipt: ScanReceipt


class IngestionAdapter(Protocol):
    source_name: str

    def fetch(self, payload) -> FetchResult: ...


# --------------------------------------------------------------- DemoAdapter


class DemoAdapter:
    """§6.2 — the judge's path. One click, no network, no auth, cannot fail.

    Reads a bundled profile from /data. The only input is a profile name, which
    is validated against a fixed tuple, so there is no user-supplied path and
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


# ----------------------------------------------------------- SmsPasteAdapter

# "VM-HDFCBK: Rs.649 debited..." — carrier prefix optional, colon required.
SENDER_LINE = re.compile(r"^(?P<sender>[A-Z]{2}-[A-Z0-9]{4,10}|[A-Z]{4,10})\s*:\s*(?P<body>.+)$")

# A real SMS wraps over a handful of lines. Above this, a blank-line-free paste
# is one-message-per-line and must NOT be joined — joining 800 lines would match
# the first pattern once and silently discard 799 transactions.
MAX_WRAPPED_LINES = 6
MAX_LLM_LINES = 40


class SmsPasteAdapter:
    """§6.3 — the hero feature. One textarea, fifteen seconds, zero permissions.

    Handles both shapes real pastes come in: one message per line, and messages
    wrapped over several lines separated by blank lines.
    """

    source_name = "sms_paste"

    def fetch(self, payload: str, use_llm: bool = True) -> FetchResult:
        receipt = ScanReceipt(source=self.source_name)
        txns: list[Transaction] = []
        unparsed: list[tuple[int, str]] = []

        for index, raw_line in enumerate(self._messages(payload)):
            receipt.scanned += 1
            sender, body = self._split_sender(raw_line)

            if sender is not None and not is_bank_sender(sender):
                receipt.ignored += 1          # OTP, promo, delivery update
                continue
            if not looks_financial(body):
                receipt.ignored += 1          # no currency token: not a txn
                continue

            parsed = parse_body(body)
            if parsed is None:
                unparsed.append((index, body))
                continue
            txns.append(self._to_txn(parsed, index))

        # §6.3: everything unmatched goes into ONE batched call, capped.
        if use_llm and unparsed:
            recovered = llm_parse_sms([b for _, b in unparsed[:MAX_LLM_LINES]])
            for offset, (index, body) in enumerate(unparsed[:MAX_LLM_LINES]):
                fields = recovered.get(offset)
                if fields:
                    txns.append(self._to_txn(fields, index, via_llm=True))
                    receipt.llm_recovered += 1

        receipt.unparsed = len(unparsed) - receipt.llm_recovered
        receipt.matched = len(txns)
        if receipt.unparsed:
            receipt.notes.append(
                f"{receipt.unparsed} bank-looking message(s) we could not read — "
                f"they are excluded from the analysis, not guessed at"
            )
        if len(unparsed) > MAX_LLM_LINES:
            receipt.notes.append(
                f"AI recovery capped at {MAX_LLM_LINES} messages per scan")
        return FetchResult(transactions=txns, receipt=receipt)

    # -- internals

    def _messages(self, payload: str) -> list[str]:
        out: list[str] = []
        for block in re.split(r"\n\s*\n", payload or ""):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            if len(lines) <= MAX_WRAPPED_LINES and len(lines) > 1:
                # Could be one wrapped message. Take it whole if that parses.
                joined = " ".join(lines)
                _, body = self._split_sender(joined)
                if parse_body(body) is not None:
                    out.append(joined)
                    continue
            out.extend(lines)
        return out

    def _split_sender(self, line: str) -> tuple[str | None, str]:
        match = SENDER_LINE.match(line.strip())
        if match:
            return match.group("sender"), match.group("body")
        return None, line.strip()

    def _to_txn(self, fields: dict, index: int, via_llm: bool = False) -> Transaction:
        return Transaction(
            date=fields["date"],
            merchant_raw=fields["merchant_raw"],
            amount=round(float(fields["amount"]), 2),
            direction=fields["direction"],
            source="sms_paste",
            source_ref=f"sms_paste:{index}" + (":ai" if via_llm else ""),
            account_hint=fields.get("account_hint"),
        )


# --------------------------------------------------- batched SMS LLM fallback

_SMS_SCHEMA = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "date": {"type": "string"},
                    "amount": {"type": "number"},
                    "merchant": {"type": "string"},
                    "direction": {"type": "string", "enum": ["debit", "credit"]},
                },
                "required": ["index", "date", "amount", "merchant", "direction"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["messages"],
    "additionalProperties": False,
}

_NUMBERS = re.compile(r"\d[\d,]*\.?\d*")


def _amount_appears_in(line: str, amount: float) -> bool:
    """The guard that keeps hallucinated money out of the pipeline.

    §6.3 calls this a reformatting task on text the model can see, which is
    true — but 'low hallucination risk' is not 'no risk', and a fabricated
    rupee figure would flow straight into the leak total. If the number the
    model returned is not literally present in the source line, drop it.
    """
    for token in _NUMBERS.findall(line):
        try:
            if abs(float(token.replace(",", "")) - amount) < 0.01:
                return True
        except ValueError:
            continue
    return False


def llm_parse_sms(lines: list[str]) -> dict[int, dict]:
    """One batched call. Returns {} on ANY failure — the caller reports the
    unparsed count honestly rather than inventing transactions."""
    if not lines or not groq_key():
        return {}

    numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(lines))
    out: dict[int, dict] = {}
    try:
        from groq import Groq

        response = Groq().chat.completions.create(
            model=GROQ_MODEL,
            temperature=0,
            response_format={"type": "json_schema", "json_schema": {
                "name": "sms_transactions", "strict": True, "schema": _SMS_SCHEMA}},
            messages=[
                {"role": "system", "content": (
                    "Extract transaction fields from Indian bank SMS. Echo the "
                    "line's index. Dates are DAY-FIRST (05-04-26 is 5 April 2026); "
                    "return them as YYYY-MM-DD. Copy the amount digits EXACTLY as "
                    "they appear — never round, convert, or infer a figure. Skip "
                    "any line that is not a completed transaction (OTPs, balance "
                    "alerts, promotions, failed payments) by omitting it."
                )},
                {"role": "user", "content": numbered},
            ],
        )
        payload = json.loads(response.choices[0].message.content)
        for item in payload["messages"]:
            i = item["index"]
            if not 0 <= i < len(lines):
                continue
            when = parse_date(item["date"])
            amount = float(item["amount"])
            merchant = (item["merchant"] or "").strip()
            if when is None or amount <= 0 or not merchant:
                continue
            if not _amount_appears_in(lines[i], amount):
                continue
            out[i] = {
                "date": when, "merchant_raw": merchant, "amount": amount,
                "direction": item["direction"], "account_hint": None,
            }
    except Exception:
        # ponytail: same contract as every other LLM call in this codebase —
        # the pipeline never cares why it failed, only that it degrades to the
        # deterministic result.
        return {}
    return out
