"""Ingestion adapters — spec §6.

The contract every adapter must hold: emit `Transaction[]` built from the frozen
§5 dataclass, plus an honest scan receipt. Nothing downstream may be able to
tell which adapter ran.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from adapters import (  # noqa: E402
    DEMO_PROFILES, DemoAdapter, FetchResult, ScanReceipt, SmsPasteAdapter,
)
from main import analyze  # noqa: E402
from models import Transaction  # noqa: E402


# ------------------------------------------------------------------ DemoAdapter


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_every_bundled_profile_loads(profile):
    """§6.2: 'cannot fail'. If a profile stops loading, the judge's path is dead."""
    result = DemoAdapter().fetch(profile)
    assert isinstance(result, FetchResult)
    assert isinstance(result.receipt, ScanReceipt)
    assert len(result.transactions) == 800
    assert all(isinstance(t, Transaction) for t in result.transactions)


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_emits_the_frozen_transaction_shape(profile):
    for t in DemoAdapter().fetch(profile).transactions:
        assert isinstance(t.date, date)
        assert t.direction in ("debit", "credit")
        assert t.source in ("demo", "sms_paste", "sms_xml", "gmail", "csv")
        assert t.amount >= 0
        assert t.merchant_raw


def test_receipt_counts_are_real(analyses=None):
    r = DemoAdapter().fetch("family").receipt
    assert r.source == "demo"
    assert r.scanned == r.matched == 800
    assert r.unparsed == 0
    # §15/§16 promises, asserted rather than printed on a slide.
    assert r.attachments_opened == 0
    assert r.bytes_stored == 0
    assert "0 attachments opened" in r.summary()
    assert "0 bytes stored" in r.summary()


def test_unknown_profile_is_rejected_not_guessed():
    with pytest.raises(ValueError, match="unknown demo profile"):
        DemoAdapter().fetch("nonexistent")
    # The only input is a name checked against a fixed tuple — no path to escape.
    with pytest.raises(ValueError):
        DemoAdapter().fetch("../../etc/passwd")


def test_demo_adapter_is_deterministic_and_stateless():
    a = DemoAdapter().fetch("student")
    b = DemoAdapter().fetch("student")
    assert a.transactions == b.transactions


def test_adapter_output_drives_the_full_pipeline():
    """The real contract: the engine takes adapter output with no adaptation."""
    result = DemoAdapter().fetch("young_professional")
    analysis = analyze(result.transactions)
    assert analysis["portfolio"]["subscription_count"] == 9
    assert analysis["portfolio"]["monthly_leak"] > 0
    assert analysis["subscriptions"][0]["action"]["kind"] in (
        "cancel", "downgrade", "renegotiate", "keep")


# --------------------------------------------------------------- SmsPasteAdapter


def sms_text(profile: str) -> str:
    return (ROOT / "data" / profile / "sms.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_paste_round_trips_the_rendered_sms(profile):
    """The real test: data_gen rendered these transactions AS SMS; the adapter
    must recover them. Same 800 transactions, reached by a different route."""
    result = SmsPasteAdapter().fetch(sms_text(profile), use_llm=False)
    r = result.receipt
    assert r.scanned == 2800
    assert r.ignored == 2000          # OTPs, promos, delivery updates
    assert r.matched == 800
    assert r.unparsed == 0, r.notes


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_paste_recovers_the_same_amounts_and_dates(profile):
    """Not just 'a transaction' — the RIGHT date, amount and merchant."""
    original = {
        (t.date, round(t.amount, 2), t.merchant_raw)
        for t in DemoAdapter().fetch(profile).transactions
    }
    recovered = {
        (t.date, round(t.amount, 2), t.merchant_raw)
        for t in SmsPasteAdapter().fetch(sms_text(profile), use_llm=False).transactions
    }
    assert recovered == original


def test_paste_output_is_indistinguishable_downstream():
    """§6: nothing downstream may know which adapter ran."""
    demo = analyze(DemoAdapter().fetch("young_professional").transactions)
    pasted = analyze(
        SmsPasteAdapter().fetch(sms_text("young_professional"), use_llm=False).transactions)
    assert {s["canonical"] for s in pasted["subscriptions"]} == \
           {s["canonical"] for s in demo["subscriptions"]}
    assert pasted["portfolio"]["monthly_leak"] == demo["portfolio"]["monthly_leak"]


def test_one_message_per_line_is_never_joined():
    """Regression guard: joining a blank-line-free paste would match the first
    pattern once and silently discard everything after it."""
    lines = sms_text("student").splitlines()[:400]
    result = SmsPasteAdapter().fetch("\n".join(lines), use_llm=False)
    assert result.receipt.matched > 50, "800 lines collapsed into a handful"


def test_wrapped_multiline_message_is_parsed_whole():
    """Android pastes often wrap one SMS over several lines."""
    wrapped = (
        "VM-HDFCBK: Rs.649.00 debited from a/c XX4471\n"
        "on 14-03-26 to UPI/NETFLIX BILLDESK/928471/PAYMENT\n"
        "via NetBanking. Not you? Call 18002586161"
    )
    result = SmsPasteAdapter().fetch(wrapped, use_llm=False)
    assert result.receipt.matched == 1
    t = result.transactions[0]
    assert t.amount == 649.0
    assert t.date == date(2026, 3, 14)


def test_dates_are_day_first():
    """05-04-26 is 5 April in every Indian bank template, 4 May to a US parser."""
    body = "Rs.500.00 debited from a/c XX4471 on 05-04-26 to TEST MERCHANT via UPI"
    t = SmsPasteAdapter().fetch(body, use_llm=False).transactions[0]
    assert t.date == date(2026, 4, 5)


def test_non_financial_lines_are_ignored_not_counted_as_unparsed():
    """The receipt must not overstate what we failed to read."""
    paste = "\n".join([
        "VM-AMAZON: Your OTP for Amazon login is 133919. Do not share it.",
        "AD-SWIGGY: Your order has been delivered. Rate your experience!",
        "TX-PAYTM1: MEGA SALE! Upto 45% off. Shop now.",
    ])
    r = SmsPasteAdapter().fetch(paste, use_llm=False).receipt
    assert r.scanned == 3 and r.ignored == 3
    assert r.unparsed == 0 and r.matched == 0


def test_unreadable_bank_message_is_reported_not_guessed():
    paste = "VM-HDFCBK: Rs.1,234.00 was moved somewhere on some day, somehow"
    r = SmsPasteAdapter().fetch(paste, use_llm=False).receipt
    assert r.matched == 0
    assert r.unparsed == 1
    assert any("could not read" in n for n in r.notes)


def test_credit_direction_is_detected():
    body = ("VM-HDFCBK: Rs.95,000.00 credited to a/c XX4471 on 01-05-26 "
            "by SALARY ACME TECHNOLOGIES PVT LTD 545320. Avl Bal INR 3,04,000.00.")
    t = SmsPasteAdapter().fetch(body, use_llm=False).transactions[0]
    assert t.direction == "credit"
    assert t.amount == 95000.0


def test_new_patterns_cover_the_banks_section_6_3_names():
    samples = {
        "Sent Rs.450.00 from Kotak Bank AC X1234 to SWIGGY on 12-05-26": 450.0,
        "Rs.320 paid to ZOMATO via UPI on 03-06-26": 320.0,
        "Rs.1,499.00 debited from A/c XX8821 on 15-02-26 for AMAZON PRIME.": 1499.0,
        "Your Card XX2210 has been used for Rs.649.00 at NETFLIX on 14-03-26": 649.0,
        "Rs.5,000.00 auto-debited from XX4471 towards SIP GROWW on 10-04-26": 5000.0,
    }
    for body, expected in samples.items():
        result = SmsPasteAdapter().fetch(body, use_llm=False)
        assert result.receipt.matched == 1, f"no pattern matched: {body}"
        assert result.transactions[0].amount == expected, body


def test_zero_amount_trial_charge_is_not_dropped():
    """Regression: a Rs 0 free-trial charge is a REAL transaction (§13).

    Treating amount<=0 as a parse failure silently deleted the student
    profile's ChatGPT Plus trial — the charge the whole trial-conversion
    dormancy signal is built on.
    """
    body = ("JD-AXISBK: Rs 0.00 debited from A/c XX8821 "
            "UPI/OPENAI/699681/PAYMENT on 22-01-25")
    result = SmsPasteAdapter().fetch(body, use_llm=False)
    assert result.receipt.matched == 1
    assert result.transactions[0].amount == 0.0


REAL_WORLD_SMS = [
    "VM-HDFCBK: Sent Rs.500.00 From HDFC Bank A/C x1234 To John Doe On 12/05/26 Ref 512345",
    "VM-HDFCBK: Alert: You've spent Rs.649.00 via Debit Card xx1234 at NETFLIX.COM on 14-03-26",
    "JD-SBIINB: Dear SBI User, your A/c X1234-debited by Rs.299.0 on 21Mar26 transfer to HOTSTAR Ref No 5123",
    "VM-AXISBK: Spent Card no. XX1234 INR 1675 on 05-04-26 ADOBE SYSTEMS Avl Lmt INR 84325",
    "AD-KOTAKB: Rs.99.00 debited from Kotak Bank A/c X1234 on 11-05-26 to JIOSAAVN. UPI Ref 5123.",
    "VM-PAYTM: Paid Rs.320 to Zomato on 12-05-26. UPI Ref: 512345678901. -Paytm",
    "AD-PHONPE: You paid Rs.450 to Swiggy on 12-05-26. UPI transaction ID 512345678901",
    "BP-BOBTXN: Rs.1349.00 debited from A/c XX1234 on 04-06-26 towards ACT FIBERNET. Avl Bal Rs.45000",
    "AD-CANBNK: An amount of INR 1,999.00 has been DEBITED to your account XX1234 on 23-06-26 towards OPENAI",
    "VM-IDFCFB: INR 199 debited from IDFC FIRST Bank A/c XXXX1234 on 06-Jun-26. Info: UPI/ZEE5. Avl Bal INR 12,345",
    "AD-YESBNK: Rs 129.00 has been debited from your account XX1234 towards YOUTUBE PREMIUM on 08-04-26",
]


def test_real_world_sms_shapes_parse_without_the_llm():
    """The honest measurement: formats our own generator never produced.

    The template bank alone scored 0/12 on these — every real bank varies the
    wording ("debited with", "debited by", "Sent Rs.X From ... To"). The
    field-role tier is what makes the SMS path actually work on real pastes,
    and it must keep working without any network call.
    """
    result = SmsPasteAdapter().fetch("\n".join(REAL_WORLD_SMS), use_llm=False)
    assert result.receipt.matched >= 10, (
        f"deterministic parse rate regressed: {result.receipt.matched}/11\n"
        f"{result.receipt.notes}")
    assert result.receipt.ignored == 0, "real bank senders must not be ignored"

    by_merchant = {t.merchant_raw.upper(): t for t in result.transactions}
    assert any("NETFLIX" in m for m in by_merchant)
    assert any("OPENAI" in m for m in by_merchant)
    assert any("ZEE5" in m for m in by_merchant)
    # Day-first, not month-first.
    netflix = next(t for t in result.transactions if "NETFLIX" in t.merchant_raw.upper())
    assert netflix.date == date(2026, 3, 14) and netflix.amount == 649.0


def test_upi_app_senders_are_recognised():
    """§6.3 names 'generic UPI app receipts' — Paytm/PhonePe are not banks."""
    from sms_patterns import is_bank_sender
    assert is_bank_sender("VM-PAYTM") and is_bank_sender("AD-PHONPE")
    assert not is_bank_sender("AD-MYNTRA")


def test_hallucinated_amounts_are_rejected():
    """The one place a fabricated rupee figure could enter financial data."""
    from adapters import _amount_appears_in
    line = "VM-HDFCBK: Rs.1,499.00 debited on 14-03-26"
    assert _amount_appears_in(line, 1499.0)
    assert not _amount_appears_in(line, 14990.0)
    assert not _amount_appears_in(line, 999.0)


def test_llm_failure_leaves_the_count_honest(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    monkeypatch.setitem(sys.modules, "groq", type(sys)("groq"))

    def explode(*a, **kw):
        raise RuntimeError("429 rate_limit_exceeded")
    sys.modules["groq"].Groq = explode

    paste = "VM-HDFCBK: Rs.1,234.00 moved somewhere on some day, somehow"
    r = SmsPasteAdapter().fetch(paste, use_llm=True).receipt
    assert r.matched == 0 and r.unparsed == 1 and r.llm_recovered == 0


def test_data_directory_is_present():
    """Guards the deployment failure that kills the judge's path silently.

    /data must be committed — Render clones the repo, and a missing profile
    turns the one-click demo into a 500 with no local symptom.
    """
    for profile in DEMO_PROFILES:
        path = ROOT / "data" / profile / "transactions.json"
        assert path.exists(), f"missing bundled profile: {path}"
