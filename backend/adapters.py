"""Ingestion adapters — spec §6.

Five implementations, one interface. Nothing downstream knows or cares which
ran: they all emit `Transaction[]` built from the same frozen §5 dataclass.

    DemoAdapter      bundled profiles, zero network
    SmsPasteAdapter  pasted bank SMS
    SmsXmlAdapter    SMS Backup & Restore export
    CsvAdapter       date/description/amount/type
    GmailAdapter     parses fetched messages; OAuth transport deferred (§3.2)

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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from rapidfuzz import fuzz

from config import GROQ_MODEL, groq_client, groq_key
from models import Transaction
from sms_patterns import (
    is_bank_sender, looks_financial, parse_body, parse_date, strip_carrier,
)

# India Standard Time. SMS Backup & Restore stores epoch milliseconds, and
# converting those in server-local time puts a 00:30 IST message on the
# previous day the moment this runs on Render (UTC).
IST = timezone(timedelta(hours=5, minutes=30))

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
        """Split a paste into messages.

        A line that parses on its own IS a message — joining is only ever a
        recovery for lines that don't. An earlier version joined any block of
        <= 6 lines on the theory it might be one wrapped SMS, which silently
        collapsed three independent one-per-line messages into one. Small
        pastes are exactly what Android's copy produces, so that was the common
        case, not the edge case.
        """
        out: list[str] = []
        for block in re.split(r"\n\s*\n", payload or ""):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            i = 0
            while i < len(lines):
                _, body = self._split_sender(lines[i])

                # Stands alone, or is not a bank message at all (an OTP, a
                # promo). Either way it is one message — growing a
                # non-financial line would swallow the bank SMS after it.
                if parse_body(body) is not None or not looks_financial(body):
                    out.append(lines[i])
                    i += 1
                    continue

                # Financial but incomplete — grow a wrapped message, stopping
                # at the next sender ID, which always starts a new message.
                grown = None
                limit = min(MAX_WRAPPED_LINES, len(lines) - i)
                for span in range(2, limit + 1):
                    if SENDER_LINE.match(lines[i + span - 1]):
                        break
                    candidate = " ".join(lines[i:i + span])
                    _, candidate_body = self._split_sender(candidate)
                    if parse_body(candidate_body) is not None:
                        grown = (candidate, span)
                        break

                if grown:
                    out.append(grown[0])
                    i += grown[1]
                else:
                    out.append(lines[i])
                    i += 1
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


# ------------------------------------------------------------ SmsXmlAdapter

MAX_UPLOAD_BYTES = 40 * 1024 * 1024      # a 50k-message export is ~15MB
MAX_XML_ELEMENTS = 200_000


class SmsXmlAdapter:
    """§6.4 — SMS Backup & Restore export. The high-volume path.

    The app is already installed on a large share of Indian phones and exports
    the entire message history, so accepting this file IS our "connect SMS":
    one file picker, thousands of real bank messages, zero permissions.

    Bodies go through the same parser as the paste adapter.
    """

    source_name = "sms_xml"

    def fetch(self, payload: bytes | str, use_llm: bool = True) -> FetchResult:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError(
                f"file is {len(raw) / 1e6:.0f}MB; the limit is "
                f"{MAX_UPLOAD_BYTES / 1e6:.0f}MB")

        receipt = ScanReceipt(source=self.source_name)
        txns: list[Transaction] = []
        unparsed: list[tuple[int, str]] = []

        for index, (sender, body, stamp) in enumerate(self._messages(raw)):
            receipt.scanned += 1

            # Sender IDs carry a carrier prefix — VM-, AD-, JD-, BP- (§6.4).
            if not is_bank_sender(sender):
                receipt.ignored += 1
                continue
            if not looks_financial(body):
                receipt.ignored += 1
                continue

            parsed = parse_body(body)
            if parsed is None:
                unparsed.append((index, body))
                continue

            # The bank's own stated date beats the phone's receipt timestamp:
            # it has no timezone to get wrong, and it is what the user sees.
            if parsed.get("date") is None and stamp is not None:
                parsed["date"] = stamp
            txns.append(self._to_txn(parsed, index))

        if use_llm and unparsed:
            recovered = llm_parse_sms([b for _, b in unparsed[:MAX_LLM_LINES]])
            for offset, (index, _) in enumerate(unparsed[:MAX_LLM_LINES]):
                fields = recovered.get(offset)
                if fields:
                    txns.append(self._to_txn(fields, index, via_llm=True))
                    receipt.llm_recovered += 1

        receipt.unparsed = len(unparsed) - receipt.llm_recovered
        receipt.matched = len(txns)
        if receipt.unparsed:
            receipt.notes.append(
                f"{receipt.unparsed} bank message(s) we could not read — "
                f"excluded from the analysis, not guessed at")
        return FetchResult(transactions=txns, receipt=receipt)

    def _messages(self, raw: bytes):
        """Hardened streaming parse.

        An uploaded XML file is untrusted input and the classic
        billion-laughs / XXE target. lxml is already a dependency, so the
        hardened parser costs nothing; entities are not resolved, the network
        is never touched, and elements are cleared as we go so a huge export
        does not sit in memory twice.
        """
        from io import BytesIO

        from lxml import etree

        seen = 0
        try:
            # lxml's iterparse takes the hardening options directly — it does
            # NOT accept a pre-built parser object.
            for _, el in etree.iterparse(
                BytesIO(raw),
                events=("end",),
                tag="sms",
                resolve_entities=False,
                no_network=True,
                huge_tree=False,
                load_dtd=False,
                dtd_validation=False,
            ):
                seen += 1
                if seen > MAX_XML_ELEMENTS:
                    el.clear()
                    break
                body = el.get("body") or ""
                sender = strip_carrier(el.get("address") or "")
                stamp = self._stamp(el.get("date"))
                el.clear()
                while el.getprevious() is not None:
                    del el.getparent()[0]
                if body:
                    yield sender, body, stamp
        except etree.XMLSyntaxError:
            # The raw lxml message ("Start tag expected, '<' not found, line 1,
            # column 1") means nothing to someone who picked the wrong file.
            raise ValueError(
                "That doesn't look like an SMS Backup & Restore export. "
                "It should be a .xml file whose contents start with <smses>."
            ) from None

    @staticmethod
    def _stamp(value: str | None):
        if not value:
            return None
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=IST).date()
        except (ValueError, OverflowError, OSError):
            return None

    def _to_txn(self, fields: dict, index: int, via_llm: bool = False) -> Transaction:
        return Transaction(
            date=fields["date"],
            merchant_raw=fields["merchant_raw"],
            amount=round(float(fields["amount"]), 2),
            direction=fields["direction"],
            source="sms_xml",
            source_ref=f"sms_xml:{index}" + (":ai" if via_llm else ""),
            account_hint=fields.get("account_hint"),
        )


# --------------------------------------------------------------- CsvAdapter

MAX_CSV_ROWS = 50_000

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
    """§6.6 — cheap fallback for the judge who happens to have a statement."""

    source_name = "csv"

    def fetch(self, payload: bytes | str) -> FetchResult:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError("file too large")

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
            receipt.notes.append(f"{receipt.unparsed} row(s) had no readable date or amount")
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


# -------------------------------------------------------------- GmailAdapter


class GmailAdapter:
    """§6.5 — parses already-fetched Gmail messages.

    The OAuth transport is deliberately not here: §3.2 concedes a judge cannot
    clear the unverified-app interstitial, so the adapter is fed bundled demo
    receipts today and would be fed a real `messages.get` response unchanged.

    Note what this class never references: attachments. Not a flag, not a
    filter — there is no code path that could open one, which is what makes the
    consent copy structurally true rather than a promise.
    """

    source_name = "gmail"

    def fetch(self, payload: list[dict], use_llm: bool = True) -> FetchResult:
        receipt = ScanReceipt(source=self.source_name)
        txns: list[Transaction] = []
        unparsed: list[tuple[int, str]] = []

        for index, message in enumerate(payload or []):
            receipt.scanned += 1
            # snippet + text/plain only (§6.5)
            body = str(message.get("body_text") or message.get("snippet") or "")
            subject = str(message.get("subject") or "")
            haystack = f"{subject}\n{body}"

            if not looks_financial(haystack):
                receipt.ignored += 1
                continue

            parsed = parse_body(body) or parse_body(haystack)
            if parsed is None:
                unparsed.append((index, body[:400]))
                continue

            if parsed.get("date") is None:
                parsed["date"] = parse_date(str(message.get("date") or ""))
            if parsed["date"] is None:
                unparsed.append((index, body[:400]))
                continue
            txns.append(self._to_txn(parsed, message, index))

        if use_llm and unparsed:
            recovered = llm_parse_sms([b for _, b in unparsed[:MAX_LLM_LINES]])
            for offset, (index, _) in enumerate(unparsed[:MAX_LLM_LINES]):
                fields = recovered.get(offset)
                if fields:
                    txns.append(self._to_txn(fields, payload[index], index, via_llm=True))
                    receipt.llm_recovered += 1

        receipt.unparsed = len(unparsed) - receipt.llm_recovered
        receipt.matched = len(txns)
        receipt.notes.append("Read the plain-text body only — no attachment was opened")
        return FetchResult(transactions=txns, receipt=receipt)

    def _to_txn(self, fields: dict, message: dict, index: int,
                via_llm: bool = False) -> Transaction:
        ref = str(message.get("id") or index)
        return Transaction(
            date=fields["date"],
            merchant_raw=fields["merchant_raw"],
            amount=round(float(fields["amount"]), 2),
            direction=fields["direction"],
            source="gmail",
            source_ref=f"gmail:{ref}" + (":ai" if via_llm else ""),
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
        response = groq_client().chat.completions.create(
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
