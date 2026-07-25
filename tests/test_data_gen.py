"""Internal-consistency checks for the generated corpus (spec §13).

These assertions compute everything independently — deltas, price steps, periods.
They must NOT import any detector, or they stop being a check and become a mirror.
"""

import json
import re
import statistics
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import data_gen  # noqa: E402
from models import Transaction  # noqa: E402

PROFILES = [p.name for p in data_gen.PROFILES]
PERIOD_BANDS = {  # spec §8 snap_to_period
    "weekly": (5, 9), "monthly": (28, 32), "quarterly": (88, 95), "annual": (355, 370),
}


def load(profile: str, name: str):
    path = ROOT / "data" / profile / name
    if name.endswith(".txt"):
        return path.read_text(encoding="utf-8").splitlines()
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=PROFILES)
def corpus(request):
    p = request.param
    return {
        "name": p,
        "txns": load(p, "transactions.json"),
        "gt": load(p, "ground_truth.json"),
    }


def tpl_to_regex(tpl: str) -> re.Pattern:
    """Template with {ref6}/{ref4}/{card}/{city} placeholders -> matching regex."""
    parts = re.split(r"(\{ref6\}|\{ref4\}|\{card\}|\{city\})", tpl)
    out = ""
    for part in parts:
        if part == "{ref6}":
            out += r"\d{6}"
        elif part == "{ref4}":
            out += r"\d{4}"
        elif part == "{card}":
            out += r"\d{4}"
        elif part == "{city}":
            out += r"[A-Z]+"
        else:
            out += re.escape(part)
    return re.compile(f"^{out}$")


def series_for(txns, variants):
    """All transactions whose raw string matches any of a merchant's templates."""
    pats = [tpl_to_regex(v) for v in variants]
    hits = [t for t in txns if any(p.match(t["merchant_raw"]) for p in pats)]
    return sorted(hits, key=lambda t: t["date"])


# --------------------------------------------------------------------- structure


def test_records_match_frozen_model(corpus):
    for rec in corpus["txns"]:
        t = Transaction(**{**rec, "date": date.fromisoformat(rec["date"])})
        assert t.direction in ("debit", "credit")
        assert t.source in ("demo", "csv")
        assert t.amount >= 0
        assert data_gen.START_DATE <= t.date <= data_gen.END_DATE


def test_volume(corpus):
    gt = corpus["gt"]
    assert 750 <= gt["transaction_count"] <= 950, gt["transaction_count"]
    assert gt["noise_count"] >= 400, gt["noise_count"]
    assert 7 <= len(gt["subscriptions"]) <= 9
    assert gt["transaction_count"] == len(corpus["txns"])


def test_only_the_trial_is_free(corpus):
    zero = [t for t in corpus["txns"] if t["amount"] == 0]
    trials = corpus["gt"]["trial_conversions"]
    assert len(zero) <= len(trials)
    # ChatGPT Plus in the student profile is deliberately Rs 0 — it is the
    # divide-by-zero case for §9's abs(nxt-cur)/cur.
    if corpus["name"] == "student":
        assert any(t["trial_amount"] == 0.0 for t in trials)


# ------------------------------------------------------------------ subscriptions


def test_every_raw_variant_actually_appears(corpus):
    for sub in corpus["gt"]["subscriptions"]:
        for variant in sub["raw_variants"]:
            pat = tpl_to_regex(variant)
            assert any(pat.match(t["merchant_raw"]) for t in corpus["txns"]), \
                f"{sub['canonical']}: template never rendered -> {variant}"


def test_variant_count_stresses_the_normalizer(corpus):
    for sub in corpus["gt"]["subscriptions"]:
        n = len(sub["raw_variants"])
        # An annual sub charges twice in 18 months, so 2 variants is its ceiling.
        expected_min = 2 if sub["period"] == "annual" else 3
        assert expected_min <= n <= 4, f"{sub['canonical']}: {n} variants"
        assert n <= sub["occurrences"], "cannot show more variants than charges"


def test_occurrence_gate(corpus):
    for sub in corpus["gt"]["subscriptions"]:
        hits = series_for(corpus["txns"], sub["raw_variants"])
        assert len(hits) == sub["occurrences"]
        assert len(hits) >= sub["min_occurrences_required"], sub["canonical"]
        if sub["period"] == "annual":
            assert sub["min_occurrences_required"] == 2, \
                "18 months cannot hold 3 annual charges; the >=3 gate must relax"


def test_median_delta_lands_in_declared_period_band(corpus):
    for sub in corpus["gt"]["subscriptions"]:
        hits = series_for(corpus["txns"], sub["raw_variants"])
        dates = sorted(date.fromisoformat(t["date"]) for t in hits)
        deltas = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        med = statistics.median(deltas)
        lo, hi = PERIOD_BANDS[sub["period"]]
        assert lo <= med <= hi, f"{sub['canonical']} {sub['period']}: median {med}"


# ------------------------------------------------------------------ price changes


def test_declared_price_changes_really_happened(corpus):
    subs = {s["canonical"]: s for s in corpus["gt"]["subscriptions"]}
    for chg in corpus["gt"]["price_changes"]:
        hits = series_for(corpus["txns"], subs[chg["canonical"]]["raw_variants"])
        on = chg["changed_on"]
        before = [t for t in hits if t["date"] < on]
        after = [t for t in hits if t["date"] >= on]
        assert before and after, chg
        assert before[-1]["amount"] == pytest.approx(chg["from_amount"])
        assert after[0]["amount"] == pytest.approx(chg["to_amount"])


def test_step_hikes_persist(corpus):
    """A hike that doesn't hold is proration, not a price change (§9)."""
    subs = {s["canonical"]: s for s in corpus["gt"]["subscriptions"]}
    for chg in corpus["gt"]["price_changes"]:
        if chg["kind"] != "step":
            continue
        hits = series_for(corpus["txns"], subs[chg["canonical"]]["raw_variants"])
        after = [t["amount"] for t in hits if t["date"] >= chg["changed_on"]]
        assert len(after) >= 3, f"{chg['canonical']}: hike needs 2 following charges"
        assert all(a == pytest.approx(chg["to_amount"]) for a in after[:3])


def test_creep_is_three_same_direction_hikes_over_15pct(corpus):
    creeps = [c for c in corpus["gt"]["price_changes"] if c["kind"] == "creep"]
    assert creeps, "every profile carries one creep"
    by_merchant = {}
    for c in creeps:
        by_merchant.setdefault(c["canonical"], []).append(c)
    for canonical, chgs in by_merchant.items():
        assert len(chgs) >= 3, canonical
        assert all(c["pct"] > 0 for c in chgs), "same direction"
        cumulative = chgs[-1]["to_amount"] / chgs[0]["from_amount"] - 1
        assert cumulative > 0.15, f"{canonical}: cumulative {cumulative:.1%}"


def test_two_step_hikes_per_profile(corpus):
    steps = {c["canonical"] for c in corpus["gt"]["price_changes"] if c["kind"] == "step"}
    assert len(steps) == 2, steps


def test_trial_converts_to_full_price(corpus):
    subs = {s["canonical"]: s for s in corpus["gt"]["subscriptions"]}
    trials = corpus["gt"]["trial_conversions"]
    assert len(trials) == 1
    for tr in trials:
        hits = series_for(corpus["txns"], subs[tr["canonical"]]["raw_variants"])
        assert hits[0]["amount"] == pytest.approx(tr["trial_amount"])
        assert hits[0]["amount"] in (0.0, 1.0)
        assert hits[1]["amount"] == pytest.approx(tr["full_amount"])


def test_forgotten_annual_and_redundant_pair_present(corpus):
    gt = corpus["gt"]
    assert gt["forgotten_annual"], "spec §13 requires a forgotten annual renewal"
    subs = {s["canonical"]: s for s in gt["subscriptions"]}
    for canonical in gt["forgotten_annual"]:
        assert subs[canonical]["period"] == "annual"
    assert gt["redundant_pairs"]
    for a, b in gt["redundant_pairs"]:
        assert subs[a]["category"] == subs[b]["category"], (a, b)


# ----------------------------------------------------------------------- decoys


def test_all_six_decoy_classes_present(corpus):
    reasons = {e["reason"] for e in corpus["gt"]["excluded"]}
    assert reasons == {"rent", "salary", "emi", "sip", "cc_bill", "utility"}
    emis = [e for e in corpus["gt"]["excluded"] if e["reason"] == "emi"]
    assert len(emis) == 2, "spec §13 asks for two EMIs"


def test_decoys_look_exactly_like_subscriptions(corpus):
    """The SIP is the sharpest decoy: fixed amount, perfectly monthly."""
    sip = next(e for e in corpus["gt"]["excluded"] if e["reason"] == "sip")
    hits = series_for(corpus["txns"], sip["raw_variants"])
    assert len(hits) >= 3
    assert len({t["amount"] for t in hits}) == 1, "SIP amount must be fixed"


def test_salary_is_the_only_credit(corpus):
    credits = [t for t in corpus["txns"] if t["direction"] == "credit"]
    assert credits, "a salary/stipend credit must exist"
    salary = next(e for e in corpus["gt"]["excluded"] if e["reason"] == "salary")
    assert salary["direction"] == "credit"
    assert len(credits) == salary["occurrences"]


# ------------------------------------------------------------------ determinism


def test_generation_is_deterministic():
    """Committed corpus is a test set. If it drifts, the eval numbers are fiction."""
    p = data_gen.PROFILES[0]
    assert data_gen.generate(p) == data_gen.generate(p)


def test_committed_files_match_generator():
    for p in data_gen.PROFILES:
        fresh = data_gen.generate(p)
        assert fresh["transactions"] == load(p.name, "transactions.json"), \
            f"{p.name}: data/ is stale — rerun python backend/data_gen.py"
        assert fresh["ground_truth"] == load(p.name, "ground_truth.json")
