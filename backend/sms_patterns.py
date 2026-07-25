"""Indian bank SMS pattern bank — spec §6.3. Constants only, no parser.

Shared by data_gen.py (renders SMS) and the Phase 2 SMS adapters (parses them).
One source of truth so the generator and the parser cannot drift apart.

Each pattern must expose named groups: amt, merch, date. `acct` is optional.
"""

import re

# Sender IDs carry a carrier prefix (VM-, AD-, JD-, BP-) — strip before matching.
CARRIER_PREFIX = re.compile(r"^[A-Z]{2}-")

BANK_SENDERS = {
    "HDFCBK", "ICICIB", "SBIINB", "AXISBK", "KOTAKB", "PNBSMS",
    "BOBTXN", "CANBNK", "IDFCFB", "YESBNK", "INDUSB", "AUBANK",
}


def strip_carrier(sender: str) -> str:
    return CARRIER_PREFIX.sub("", sender.strip().upper())


def is_bank_sender(sender: str) -> bool:
    return strip_carrier(sender) in BANK_SENDERS


SMS_PATTERNS = [
    # HDFC net-banking debit
    re.compile(
        r"Rs\.?(?P<amt>[\d,]+\.?\d*)\s+debited from a/c\s+(?P<acct>[X\d]+)"
        r"\s+on\s+(?P<date>[\d\-/]+)\s+to\s+(?P<merch>.+?)\s+via",
        re.I,
    ),
    # ICICI / Axis card spend
    re.compile(
        r"INR\s+(?P<amt>[\d,]+\.?\d*)\s+spent on\s+.*?Card\s+(?P<acct>[X\d]+)"
        r"\s+at\s+(?P<merch>.+?)\s+on\s+(?P<date>[\w\-]+)",
        re.I,
    ),
    # SBI / Canara ACH-NACH mandate debit
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+debited towards\s+(?P<merch>.+?)"
        r"\s+on\s+(?P<date>[\d/\-]+)",
        re.I,
    ),
    # Axis / Kotak UPI debit
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+debited from A/c\s+(?P<acct>[X\d]+)"
        r"\s+(?P<merch>UPI/.+?)\s+on\s+(?P<date>[\d\-/]+)",
        re.I,
    ),
    # PNB / BoB / IDFC POS purchase
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+spent via\s+(?P<acct>[X\d]+)"
        r"\s+at\s+(?P<merch>.+?)\s+on\s+(?P<date>[\d\-/]+)",
        re.I,
    ),
    # Yes / IndusInd / AU standing instruction
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+has been debited for\s+(?P<merch>.+?)"
        r"\s+on\s+(?P<date>[\d\-/]+)\s+from\s+(?P<acct>[X\d]+)",
        re.I,
    ),
    # ATM cash withdrawal
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+withdrawn from\s+(?P<merch>ATM.*?)"
        r"\s+a/c\s+(?P<acct>[X\d]+)\s+on\s+(?P<date>[\d\-/]+)",
        re.I,
    ),
    # Credit (salary, refunds)
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+credited to a/c\s+(?P<acct>[X\d]+)"
        r"\s+on\s+(?P<date>[\d\-/]+)\s+by\s+(?P<merch>.+?)\.",
        re.I,
    ),
    # --- added for real-world paste coverage (§6.3) -----------------------
    # Kotak "Sent Rs.X from Kotak Bank AC X to merchant on DATE"
    re.compile(
        r"Sent\s+Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+from\s+(?:Kotak\s+Bank\s+)?"
        r"(?:AC\s+)?(?P<acct>[X\d]+)\s+to\s+(?P<merch>.+?)\s+on\s+(?P<date>[\d\-/]+)",
        re.I,
    ),
    # GPay / PhonePe / Paytm receipt: "Rs.X paid to MERCHANT on DATE"
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+paid to\s+(?P<merch>.+?)"
        r"(?:\s+via\s+\w+)?\s+on\s+(?P<date>[\d\-/]+)",
        re.I,
    ),
    # BoB / Canara: "debited from A/c X on DATE for MERCHANT"
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+debited from\s+(?:A/c\s+)?(?P<acct>[X\d]+)"
        r"\s+on\s+(?P<date>[\d\-/]+)\s+for\s+(?P<merch>[^.]+?)(?:\.|$)",
        re.I,
    ),
    # "Your Card XX1234 has been used for Rs.X at MERCHANT on DATE"
    re.compile(
        r"Card\s+(?P<acct>[X\d]+)\s+(?:has been\s+)?used for\s+"
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+at\s+(?P<merch>.+?)\s+on\s+(?P<date>[\w\-/]+)",
        re.I,
    ),
    # NACH / e-mandate auto-debit
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+(?:has been\s+)?auto[-\s]?debited"
        r"(?:\s+from\s+(?P<acct>[X\d]+))?\s+(?:towards|for)\s+(?P<merch>.+?)"
        r"\s+on\s+(?P<date>[\d\-/]+)",
        re.I,
    ),
    # Loosest debit form — no trailing "via". Last so the stricter HDFC pattern
    # above always wins when both could match.
    re.compile(
        r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+debited from\s+(?:a/c\s+)?(?P<acct>[X\d]+)"
        r"\s+on\s+(?P<date>[\d\-/]+)\s+to\s+(?P<merch>[^.]+?)(?:\.|$)",
        re.I,
    ),
]

BANK_SENDERS |= {
    # UPI apps send transaction receipts too (§6.3 "generic UPI app receipts").
    "PAYTM", "PAYTMB", "PHONPE", "PHONEPE", "GPAYIN", "GOOGLPY",
    "AMZNPAY", "BHIMUP", "CREDCL", "RZRPAY",
}

CREDIT_HINTS = ("credited to", "credited in", "credited with", "received in",
                "deposited", "credited by")

# --------------------------------------------------------- generic extraction
#
# The template patterns above are precise but brittle: measured against real
# Indian bank SMS shapes (as opposed to our own generated corpus) they matched
# 0 of 12. Real templates vary the wording endlessly — "debited with",
# "debited by", "Sent Rs.X From ... To", "Info: UPI/X" — and chasing each one
# with its own regex is a losing game.
#
# So this second deterministic tier extracts by FIELD ROLE rather than by
# sentence shape: find the money, find the date, find the merchant by the
# preposition that introduces it. Still pure regex, still explainable, still no
# LLM — it just stops assuming we can enumerate every bank's phrasing.

AMOUNT = re.compile(r"(?:RS\.?|INR|₹)\s?(?P<amt>\d[\d,]*(?:\.\d{1,2})?)", re.I)

DATE_TOKEN = re.compile(
    r"\b(?P<date>"
    r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"          # 14-03-26, 14/03/2026
    r"|\d{1,2}[-\s]?[A-Za-z]{3}[-\s]?\d{2,4}"  # 05-Apr-26, 21Mar26, 12 May 2026
    r"|\d{4}-\d{2}-\d{2}"                      # 2026-03-14
    r")\b"
)

# Prepositions that introduce a payee. Matched as the KEYWORD ALONE, then the
# name is sliced from after it — if the capture were part of this regex, a
# greedy first match would swallow every later lead in the message. ("DEBITED to
# your account XX1234 ... towards OPENAI" consumed "towards OPENAI" inside the
# rejected account capture, so the real payee was never reachable.)
MERCHANT_LEAD = re.compile(
    r"\b(?:to|at|towards|for|in favour of|info:|vpa)\s+", re.I)
MERCHANT_SPAN = 50

# Text after the merchant that is never part of its name.
MERCHANT_STOP = re.compile(
    r"\s+(?:on|ref|refno|upi|avl|available|bal|balance|not\s+you|info|txn|trxn|"
    r"transaction|id|dated|thru|via|call|sms|to\s+block)\b.*$",
    re.I,
)

# Captures that are an account, not a payee.
ACCOUNTISH = re.compile(
    r"^(?:your\s+)?(?:a/?c|acct|account|card|vpa)\b|^[Xx*]+\d|^\d+$", re.I)


def _clean_merchant(raw: str) -> str:
    cleaned = MERCHANT_STOP.sub("", raw).strip(" .,-–—")
    cleaned = re.split(r"[.,;()]", cleaned)[0]
    # A trailing single character is the head of a word we cut mid-token
    # ("ADOBE SYSTEMS Avl Lmt" -> "ADOBE SYSTEMS A"). Merchants do not end in
    # a lone letter.
    cleaned = re.sub(r"\s+\w$", "", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" .,-–—")


def generic_parse(body: str) -> dict | None:
    """Field-role extraction. Tier 2 of 3 — runs when no template matched."""
    money = AMOUNT.search(body)
    when_match = DATE_TOKEN.search(body)
    if not money or not when_match:
        return None

    when = parse_date(when_match.group("date"))
    if when is None:
        return None
    try:
        amount = float(money.group("amt").replace(",", ""))
    except ValueError:
        return None
    if amount <= 0:
        return None

    merchant = None
    for lead in MERCHANT_LEAD.finditer(body):
        candidate = _clean_merchant(body[lead.end():lead.end() + MERCHANT_SPAN])
        # "DEBITED to your account XX1234 towards OPENAI" — skip the account,
        # keep looking for the real payee.
        if candidate and not ACCOUNTISH.match(candidate) and len(candidate) > 2:
            merchant = candidate
            break

    if merchant is None:
        # Axis-style: the merchant sits straight after the date, no preposition.
        tail = body[when_match.end():]
        after = re.match(r"[\s,:]*(?P<merch>[A-Z][A-Z0-9 .&'/-]{2,40})", tail)
        if after:
            candidate = _clean_merchant(after.group("merch"))
            if candidate and not ACCOUNTISH.match(candidate) and len(candidate) > 2:
                merchant = candidate

    if not merchant:
        return None

    lowered = body.lower()
    direction = "credit" if any(h in lowered for h in CREDIT_HINTS) else "debit"
    account = re.search(r"\b((?:[Xx*]{1,6}|A/?c\s+)\d{3,6})\b", body)

    return {
        "date": when,
        "merchant_raw": merchant,
        "amount": amount,
        "direction": direction,
        "account_hint": account.group(1).strip() if account else None,
    }

# A line with no currency token and no digits is not a bank record at all — it
# is an OTP or a promo. Counted as "ignored", never as "unparsed", so the §15
# receipt does not overstate what we failed to read.
MONEY_HINT = re.compile(r"(?:RS\.?|INR|₹)\s?[\d,]", re.I)


def looks_financial(body: str) -> bool:
    return bool(MONEY_HINT.search(body))


def parse_date(raw: str):
    """Indian bank dates: 14-03-26, 14/03/26, 05-Apr-26, 20-04-2026.

    dayfirst=True is not optional here — '05-04-26' is 5 April in every Indian
    bank template and 4 May to a US-default parser.
    """
    from datetime import date as _date

    from dateutil import parser as _parser

    try:
        parsed = _parser.parse(raw, dayfirst=True, yearfirst=False).date()
    except (ValueError, OverflowError, TypeError):
        return None
    # Reject nonsense rather than silently accepting a misparse.
    if not _date(2000, 1, 1) <= parsed <= _date(2100, 1, 1):
        return None
    return parsed


def parse_body(body: str) -> dict | None:
    """Shared by the paste and XML adapters.

    Tier 1: precise bank templates. Tier 2: generic field-role extraction.
    None means both deterministic tiers failed — only then does the caller
    consider the LLM.
    """
    match = match_sms(body)
    if match is None:
        return generic_parse(body)
    groups = match.groupdict()

    # A template can match while its captured fields fail to parse. Fall THROUGH
    # to tier 2 rather than giving up — a near-miss template must not be worse
    # than no template at all.
    when = parse_date(groups.get("date") or "")
    merchant = (groups.get("merch") or "").strip(" .,-")
    try:
        amount = float(groups["amt"].replace(",", ""))
    except (ValueError, KeyError):
        amount = -1.0
    # Rs 0 is a REAL amount here: a free-trial charge (§13). Only a negative
    # means the capture failed. generic_parse stays stricter and requires > 0,
    # because a bare "Rs 0" it stumbles on is far more likely to be a balance
    # line than a trial.
    if when is None or not merchant or amount < 0:
        return generic_parse(body)

    lowered = body.lower()
    direction = "credit" if any(h in lowered for h in CREDIT_HINTS) else "debit"

    return {
        "date": when,
        "merchant_raw": merchant,
        "amount": amount,
        "direction": direction,
        "account_hint": groups.get("acct"),
    }


def match_sms(body: str):
    """First matching pattern, or None. Returned for the Phase 2 adapters."""
    for pat in SMS_PATTERNS:
        m = pat.search(body)
        if m:
            return m
    return None
