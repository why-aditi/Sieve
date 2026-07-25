"""Phase 6 — SmsXml, Csv, Gmail adapters (§6.4-6.6) and dedup (§6.7).

The corpus renders the SAME 800 charges as SMS, as XML, as CSV and (for
subscriptions) as email receipts. So every adapter has a target it must hit
exactly, and dedup has a target that can only be met if all of them are right.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import json  # noqa: E402

from adapters import (  # noqa: E402
    DEMO_PROFILES, CsvAdapter, DemoAdapter, GmailAdapter, SmsPasteAdapter,
    SmsXmlAdapter, _match_columns,
)
from dedup import dedup  # noqa: E402
from main import analyze  # noqa: E402


def fixture(profile: str, name: str) -> bytes:
    return (ROOT / "data" / profile / name).read_bytes()


def demo_txns(profile: str):
    return DemoAdapter().fetch(profile).transactions


def key(t):
    return (t.date, round(t.amount, 2), t.merchant_raw)


# --------------------------------------------------------------- SmsXmlAdapter


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_xml_recovers_the_same_800(profile):
    result = SmsXmlAdapter().fetch(fixture(profile, "sms.xml"), use_llm=False)
    assert result.receipt.scanned == 2800
    assert result.receipt.ignored == 2000
    assert result.receipt.matched == 800
    assert result.receipt.unparsed == 0
    assert {key(t) for t in result.transactions} == {key(t) for t in demo_txns(profile)}


def test_xml_output_is_indistinguishable_downstream():
    """§6: nothing downstream may know which adapter ran."""
    xml = SmsXmlAdapter().fetch(fixture("family", "sms.xml"), use_llm=False)
    assert analyze(xml.transactions)["portfolio"] == analyze(demo_txns("family"))["portfolio"]


def test_carrier_prefixes_are_stripped_before_sender_matching():
    doc = (
        '<?xml version="1.0"?><smses count="2">'
        '<sms address="VM-HDFCBK" date="1772000000000" '
        'body="Rs.649.00 debited from a/c XX4471 on 14-03-26 to NETFLIX via UPI" />'
        '<sms address="AD-MYNTRA" date="1772000000000" '
        'body="MEGA SALE! Rs.500 off your next order" />'
        "</smses>"
    )
    r = SmsXmlAdapter().fetch(doc, use_llm=False)
    assert r.receipt.matched == 1      # VM-HDFCBK -> HDFCBK, a bank
    assert r.receipt.ignored == 1      # AD-MYNTRA -> MYNTRA, not a bank


def test_billion_laughs_is_rejected_not_expanded():
    """An uploaded XML file is untrusted input at a trust boundary."""
    bomb = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
      <!ENTITY lol "lol">
      <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
      <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
      <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
      <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
    ]>
    <smses count="1"><sms address="VM-HDFCBK" date="1772000000000" body="&lol4;" /></smses>
    """
    # Either it raises, or entities stay unresolved — never a memory blow-up.
    try:
        result = SmsXmlAdapter().fetch(bomb, use_llm=False)
    except ValueError:
        return
    for t in result.transactions:
        assert len(t.merchant_raw) < 1000


def test_oversized_upload_is_refused():
    with pytest.raises(ValueError, match="limit"):
        SmsXmlAdapter().fetch(b"<smses>" + b"x" * (41 * 1024 * 1024))


def test_garbage_is_a_clear_error_not_a_crash():
    with pytest.raises(ValueError, match="SMS Backup & Restore"):
        SmsXmlAdapter().fetch(b"this is not xml at all <<<>>>")


# ------------------------------------------------------------------ CsvAdapter


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_csv_recovers_the_same_800(profile):
    result = CsvAdapter().fetch(fixture(profile, "statement.csv"))
    assert result.receipt.matched == 800
    assert result.receipt.unparsed == 0
    assert {key(t) for t in result.transactions} == {key(t) for t in demo_txns(profile)}


def test_csv_infers_direction_from_withdrawal_vs_deposit_columns():
    """The shape HDFC and ICICI actually export — no type column at all."""
    csv = (
        "Txn Date,Narration,Withdrawal Amt.,Deposit Amt.\n"
        "14/03/26,UPI/NETFLIX BILLDESK/928471/PAYMENT,649.00,\n"
        "01/03/26,SALARY ACME TECHNOLOGIES,,\"95,000.00\"\n"
    )
    txns = CsvAdapter().fetch(csv).transactions
    assert len(txns) == 2
    debit = next(t for t in txns if t.merchant_raw.startswith("UPI"))
    credit = next(t for t in txns if "SALARY" in t.merchant_raw)
    assert debit.direction == "debit" and debit.amount == 649.0
    assert credit.direction == "credit" and credit.amount == 95000.0


def test_csv_handles_the_amount_plus_type_shape():
    csv = (
        "Date,Description,Amount,Dr/Cr\n"
        "14/03/26,NETFLIX,649.00,DR\n"
        "01/03/26,SALARY,95000.00,CR\n"
    )
    txns = CsvAdapter().fetch(csv).transactions
    assert [t.direction for t in sorted(txns, key=lambda t: t.date)] == ["credit", "debit"]


def test_column_matching_is_fuzzy():
    cols = _match_columns(["Txn Date ", "Transaction Remarks", "Withdrawal Amt.",
                           "Deposit Amt.", "Closing Balance"])
    assert cols["date"] == "Txn Date "
    assert cols["description"] == "Transaction Remarks"
    assert cols["debit"] == "Withdrawal Amt."
    assert cols["credit"] == "Deposit Amt."


def test_csv_dates_are_day_first():
    csv = "Date,Description,Amount,Type\n05/04/26,NETFLIX,649,DR\n"
    assert CsvAdapter().fetch(csv).transactions[0].date == date(2026, 4, 5)


def test_unusable_csv_says_what_it_wanted():
    with pytest.raises(ValueError, match="a date, a description and an amount"):
        CsvAdapter().fetch("foo,bar,baz\n1,2,3\n")


# ---------------------------------------------------------------- GmailAdapter


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_gmail_parses_the_bundled_receipts(profile):
    messages = json.loads(fixture(profile, "emails.json"))
    result = GmailAdapter().fetch(messages, use_llm=False)
    assert result.receipt.matched > 100
    assert result.receipt.unparsed == 0, result.receipt.notes
    assert all(t.source == "gmail" for t in result.transactions)
    assert any("no attachment was opened" in n for n in result.receipt.notes)


def test_gmail_adapter_has_no_attachment_code_path():
    """The consent copy says we never open attachments. That should be true
    because no code could, not because we remembered not to.

    Checks for the Gmail API surfaces that fetch one — prose in a docstring is
    not the thing under test.
    """
    import inspect
    import re as _re

    import adapters
    source = inspect.getsource(adapters.GmailAdapter)
    code = _re.sub(r'""".*?"""', "", source, flags=_re.S)   # strip docstrings
    code = _re.sub(r"#.*", "", code)                         # strip comments
    for surface in ("attachmentId", "attachments", ".attachment", "getAttachment"):
        assert surface not in code, f"GmailAdapter references {surface}"


# ----------------------------------------------------------------------- dedup


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_sms_plus_email_dedups_back_to_exactly_800(profile):
    """The self-checking test.

    The email receipts and the SMS describe the SAME charges. A correct dedup
    collapses the union back to the original 800 — any other number means one
    of the two adapters or the matcher is wrong, and it cannot be faked.
    """
    sms = SmsPasteAdapter().fetch(
        fixture(profile, "sms.txt").decode("utf-8"), use_llm=False).transactions
    emails = GmailAdapter().fetch(
        json.loads(fixture(profile, "emails.json")), use_llm=False).transactions
    assert len(sms) == 800 and len(emails) > 100

    kept, report = dedup(sms + emails)

    assert len(kept) == 800, (
        f"{profile}: {len(sms)} SMS + {len(emails)} emails -> {len(kept)} "
        f"(merged {report.merged}); expected 800")
    assert report.merged == len(emails)
    assert {key(t) for t in kept} == {key(t) for t in demo_txns(profile)}


def test_merged_records_keep_both_source_refs():
    """§6.7: retain both refs for the audit trail."""
    sms = SmsPasteAdapter().fetch(
        fixture("student", "sms.txt").decode("utf-8"), use_llm=False).transactions
    emails = GmailAdapter().fetch(
        json.loads(fixture("student", "emails.json")), use_llm=False).transactions
    kept, _ = dedup(sms + emails)
    joined = [t for t in kept if t.source_ref and "+" in t.source_ref]
    assert len(joined) == len(emails)
    for t in joined:
        assert "gmail:" in t.source_ref and "sms_paste:" in t.source_ref


def test_dedup_respects_all_three_thresholds():
    from models import Transaction

    def txn(day, amount, merchant, source="sms_paste", ref="a"):
        return Transaction(date=day, merchant_raw=merchant, amount=amount,
                           direction="debit", source=source, source_ref=ref,
                           account_hint=None)

    base = txn(date(2026, 3, 14), 649.0, "UPI/NETFLIX BILLDESK/928471/PAYMENT")

    # Same charge seen from email — merges.
    pair = txn(date(2026, 3, 14), 649.0, "Netflix", "gmail", "b")
    assert len(dedup([base, pair])[0]) == 1

    # Amount too far apart (> Rs 1).
    assert len(dedup([base, txn(date(2026, 3, 14), 651.0, "Netflix", "gmail", "b")])[0]) == 2
    # Date too far apart (> 24h).
    assert len(dedup([base, txn(date(2026, 3, 16), 649.0, "Netflix", "gmail", "b")])[0]) == 2
    # Different merchant entirely.
    assert len(dedup([base, txn(date(2026, 3, 14), 649.0, "Spotify", "gmail", "b")])[0]) == 2
    # Opposite direction is never the same charge.
    other = txn(date(2026, 3, 14), 649.0, "Netflix", "gmail", "b")
    assert len(dedup([base, __import__("dataclasses").replace(other, direction="credit")])[0]) == 2


def test_dedup_keeps_the_richer_merchant_string():
    """The bank rail string is what the alias table matches against."""
    from models import Transaction

    sms = Transaction(date=date(2026, 3, 14),
                      merchant_raw="UPI/NETFLIX BILLDESK/928471/PAYMENT",
                      amount=649.0, direction="debit", source="sms_paste",
                      source_ref="sms_paste:1", account_hint="XX4471")
    email = Transaction(date=date(2026, 3, 14), merchant_raw="Netflix",
                        amount=649.0, direction="debit", source="gmail",
                        source_ref="gmail:9", account_hint=None)
    kept, _ = dedup([email, sms])
    assert kept[0].merchant_raw == "UPI/NETFLIX BILLDESK/928471/PAYMENT"
    assert kept[0].account_hint == "XX4471"


def test_dedup_is_a_noop_on_a_single_source():
    txns = demo_txns("young_professional")
    kept, report = dedup(txns)
    assert report.merged == 0
    assert len(kept) == len(txns)
