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
]


def match_sms(body: str):
    """First matching pattern, or None. Returned for the Phase 2 adapters."""
    for pat in SMS_PATTERNS:
        m = pat.search(body)
        if m:
            return m
    return None
