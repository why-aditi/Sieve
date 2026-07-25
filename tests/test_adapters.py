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
    DEMO_PROFILES, CsvAdapter, DemoAdapter, FetchResult, ScanReceipt,
    _match_columns,
)
from main import analyze  # noqa: E402
from models import Transaction  # noqa: E402


def fixture(profile: str, name: str) -> bytes:
    return (ROOT / "data" / profile / name).read_bytes()


def key(t):
    return (t.date, round(t.amount, 2), t.merchant_raw)


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
        assert t.source in ("demo", "csv")
        assert t.amount >= 0
        assert t.merchant_raw


def test_receipt_counts_are_real():
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


def test_data_directory_is_present():
    """Guards the deployment failure that kills the judge's path silently.

    /data must be committed — Render clones the repo, and a missing profile
    turns the one-click demo into a 500 with no local symptom.
    """
    for profile in DEMO_PROFILES:
        for name in ("transactions.json", "statement.csv"):
            path = ROOT / "data" / profile / name
            assert path.exists(), f"missing bundled fixture: {path}"


# ------------------------------------------------------------------- CsvAdapter


@pytest.mark.parametrize("profile", DEMO_PROFILES)
def test_csv_recovers_the_same_800(profile):
    """The statement renders the same charges the corpus holds — so the CSV
    path must reproduce them exactly, not approximately."""
    result = CsvAdapter().fetch(fixture(profile, "statement.csv"))
    assert result.receipt.matched == 800
    assert result.receipt.unparsed == 0
    assert {key(t) for t in result.transactions} == {
        key(t) for t in DemoAdapter().fetch(profile).transactions}


def test_csv_output_is_indistinguishable_downstream():
    """§6: nothing downstream may know which adapter ran."""
    csv = CsvAdapter().fetch(fixture("family", "statement.csv"))
    demo = DemoAdapter().fetch("family")
    assert analyze(csv.transactions)["portfolio"] == analyze(demo.transactions)["portfolio"]


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
    """05/04/26 is 5 April in every Indian export, 4 May to a US parser."""
    csv = "Date,Description,Amount,Type\n05/04/26,NETFLIX,649,DR\n"
    assert CsvAdapter().fetch(csv).transactions[0].date == date(2026, 4, 5)


def test_zero_amount_row_is_not_dropped():
    """A Rs 0.00 free-trial charge is a real row (§13) — `if debit:` deletes it."""
    csv = (
        "Txn Date,Narration,Withdrawal Amt.,Deposit Amt.\n"
        "22/01/25,UPI/OPENAI/699681/PAYMENT,0.00,\n"
    )
    txns = CsvAdapter().fetch(csv).transactions
    assert len(txns) == 1 and txns[0].amount == 0.0


def test_lakh_grouped_amounts_parse():
    csv = "Date,Description,Amount,Type\n01/03/26,SALARY,\"1,85,000.00\",CR\n"
    assert CsvAdapter().fetch(csv).transactions[0].amount == 185000.0


def test_unusable_csv_says_what_it_wanted():
    with pytest.raises(ValueError, match="a date, a description and an amount"):
        CsvAdapter().fetch("foo,bar,baz\n1,2,3\n")


def test_garbage_is_a_clear_error_not_a_crash():
    with pytest.raises(ValueError):
        CsvAdapter().fetch(bytes(range(256)) * 40)


def test_oversized_upload_is_refused():
    with pytest.raises(ValueError, match="limit"):
        CsvAdapter().fetch(b"x" * (41 * 1024 * 1024))
