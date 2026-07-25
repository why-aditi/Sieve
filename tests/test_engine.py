"""Engine evaluation harness — spec §14.

Runs the full deterministic pipeline against all three labelled profiles and
reports precision / recall / F1 per capability. Run it directly to see the table:

    python -m pytest tests/test_engine.py -s -q
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import data_gen  # noqa: E402
import exclusions  # noqa: E402
import normalize  # noqa: E402
from models import Transaction  # noqa: E402
from price_change import detect_price_changes  # noqa: E402
from recurrence import PERIODS_PER_YEAR, detect_recurrence  # noqa: E402

PROFILES = [p.name for p in data_gen.PROFILES]
RECALL_FLOOR = 0.85


# --------------------------------------------------------------------- loading


def load_profile(name: str):
    d = ROOT / "data" / name
    raw = json.loads((d / "transactions.json").read_text(encoding="utf-8"))
    txns = [Transaction(**{**r, "date": date.fromisoformat(r["date"])}) for r in raw]
    gt = json.loads((d / "ground_truth.json").read_text(encoding="utf-8"))
    return txns, gt


def run_engine(txns: list[Transaction]):
    """normalize -> cluster -> exclude -> price changes -> recurrence."""
    clusters = normalize.cluster(txns, use_llm=False)
    kept, excluded = exclusions.split(clusters)

    detected = {}
    for c in kept:
        rec = detect_recurrence(c.transactions)
        if rec is None:
            continue
        changes = detect_price_changes(c.transactions, PERIODS_PER_YEAR[rec.period])
        detected[c.canonical] = {"cluster": c, "recurrence": rec, "changes": changes}
    return detected, excluded, clusters


def prf(detected: set, truth: set) -> dict:
    tp, fp, fn = len(detected & truth), len(detected - truth), len(truth - detected)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 1.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision,
            "recall": recall, "f1": f1,
            "missed": sorted(truth - detected), "spurious": sorted(detected - truth)}


def tpl_to_regex(tpl: str) -> re.Pattern:
    parts = re.split(r"(\{ref6\}|\{ref4\}|\{card\}|\{city\})", tpl)
    out = ""
    for part in parts:
        out += {"{ref6}": r"\d{6}", "{ref4}": r"\d{4}",
                "{card}": r"\d{4}", "{city}": r"[A-Z]+"}.get(part, re.escape(part))
    return re.compile(f"^{out}$")


@pytest.fixture(scope="module")
def results():
    out = {}
    for name in PROFILES:
        txns, gt = load_profile(name)
        detected, excluded, clusters = run_engine(txns)
        out[name] = {"txns": txns, "gt": gt, "detected": detected,
                     "excluded": excluded, "clusters": clusters}
    return out


# ------------------------------------------------------------------- the metrics


def test_report(results, capsys):
    """Prints the §14 table. Assertions live in the tests below."""
    lines = ["", "=" * 78, "SIEVE — DETECTION ENGINE EVALUATION (§14)", "=" * 78]

    agg = {k: [0, 0, 0] for k in ("recurrence", "hikes", "exclusions")}
    norm_hits = norm_total = 0

    for name in PROFILES:
        r = results[name]
        gt, detected = r["gt"], r["detected"]

        truth_subs = {s["canonical"] for s in gt["subscriptions"]}
        rec = prf(set(detected), truth_subs)

        truth_hikes = {(c["canonical"], round(c["from_amount"], 2),
                        round(c["to_amount"], 2)) for c in gt["price_changes"]}
        found_hikes = {(canonical, round(ch.from_amount, 2), round(ch.to_amount, 2))
                       for canonical, d in detected.items() for ch in d["changes"]}
        hike = prf(found_hikes, truth_hikes)

        truth_excl = {e["canonical"] for e in gt["excluded"]}
        excl_variants = {e["canonical"]: e["raw_variants"] for e in gt["excluded"]}
        found_excl = set()
        for ex in r["excluded"]:
            for canonical, variants in excl_variants.items():
                pats = [tpl_to_regex(v) for v in variants]
                if any(p.match(raw) for raw in ex.cluster.raw_variants for p in pats):
                    found_excl.add(canonical)
        excl = prf(found_excl, truth_excl)

        # merchant normalization: % of subscription transactions mapped correctly
        hits = total = 0
        by_raw = {}
        for c in r["clusters"]:
            for raw in c.raw_variants:
                by_raw[raw] = c.canonical
        for sub in gt["subscriptions"]:
            pats = [tpl_to_regex(v) for v in sub["raw_variants"]]
            for t in r["txns"]:
                if any(p.match(t.merchant_raw) for p in pats):
                    total += 1
                    hits += by_raw.get(t.merchant_raw) == sub["canonical"]
        norm_hits += hits
        norm_total += total

        for key, m in (("recurrence", rec), ("hikes", hike), ("exclusions", excl)):
            agg[key][0] += m["tp"]
            agg[key][1] += m["fp"]
            agg[key][2] += m["fn"]

        lines += [
            "", f"── {name} " + "─" * (74 - len(name)),
            f"  recurrence      P {rec['precision']:.2f}  R {rec['recall']:.2f}  "
            f"F1 {rec['f1']:.2f}   (tp {rec['tp']} fp {rec['fp']} fn {rec['fn']})",
            f"  price hikes     P {hike['precision']:.2f}  R {hike['recall']:.2f}  "
            f"F1 {hike['f1']:.2f}   (tp {hike['tp']} fp {hike['fp']} fn {hike['fn']})",
            f"  exclusions      P {excl['precision']:.2f}  R {excl['recall']:.2f}  "
            f"F1 {excl['f1']:.2f}   (tp {excl['tp']} fp {excl['fp']} fn {excl['fn']})",
            f"  normalization   {hits}/{total} raw strings mapped correctly "
            f"({hits / total:.1%})" if total else "",
        ]
        if rec["missed"]:
            lines.append(f"  MISSED subs:    {', '.join(rec['missed'])}")
        if rec["spurious"]:
            lines.append(f"  FALSE POSITIVES: {', '.join(rec['spurious'])}")
        if hike["missed"]:
            lines.append(f"  MISSED hikes:   {hike['missed']}")

    lines += ["", "─" * 78, "ALL PROFILES"]
    for key, (tp, fp, fn) in agg.items():
        p = tp / (tp + fp) if tp + fp else 1.0
        rc = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 1.0
        lines.append(f"  {key:<14}  P {p:.3f}  R {rc:.3f}  F1 {f1:.3f}")
    lines.append(f"  {'normalization':<14}  {norm_hits}/{norm_total} "
                 f"({norm_hits / norm_total:.1%})")
    lines += ["=" * 78, ""]

    with capsys.disabled():
        print("\n".join(lines))


@pytest.mark.parametrize("profile", PROFILES)
def test_recurrence_recall_floor(results, profile):
    r = results[profile]
    truth = {s["canonical"] for s in r["gt"]["subscriptions"]}
    m = prf(set(r["detected"]), truth)
    assert m["recall"] >= RECALL_FLOOR, (
        f"{profile}: recall {m['recall']:.2f} — missed {m['missed']}")


@pytest.mark.parametrize("profile", PROFILES)
def test_no_decoy_is_flagged_as_a_subscription(results, profile):
    """The headline claim: we never tell the user to cancel their rent."""
    r = results[profile]
    excl_variants = {e["canonical"]: e["raw_variants"] for e in r["gt"]["excluded"]}
    for canonical, variants in excl_variants.items():
        pats = [tpl_to_regex(v) for v in variants]
        for name, d in r["detected"].items():
            leaked = [raw for raw in d["cluster"].raw_variants
                      if any(p.match(raw) for p in pats)]
            assert not leaked, f"{profile}: {canonical} leaked into '{name}': {leaked}"


@pytest.mark.parametrize("profile", PROFILES)
def test_annual_subscriptions_survive_the_gate(results, profile):
    """18 months holds 2 annual charges — the >=3 gate must relax or recall halves."""
    r = results[profile]
    annual = [s["canonical"] for s in r["gt"]["subscriptions"]
              if s["period"] == "annual"]
    assert annual
    for canonical in annual:
        assert canonical in r["detected"], f"{profile}: annual {canonical} dropped"


@pytest.mark.parametrize("profile", PROFILES)
def test_trial_conversion_does_not_crash_or_register_as_a_hike(results, profile):
    """§9's abs(nxt-cur)/cur divides by zero on the student profile's Rs 0 trial."""
    r = results[profile]
    for trial in r["gt"]["trial_conversions"]:
        assert trial["canonical"] in r["detected"], trial["canonical"]
        changes = r["detected"][trial["canonical"]]["changes"]
        assert not any(c.from_amount <= 1.0 for c in changes), \
            "trial conversion must not be reported as a price hike"


@pytest.mark.parametrize("profile", PROFILES)
def test_detected_periods_match_ground_truth(results, profile):
    r = results[profile]
    for sub in r["gt"]["subscriptions"]:
        if sub["canonical"] not in r["detected"]:
            continue
        assert r["detected"][sub["canonical"]]["recurrence"].period == sub["period"], \
            sub["canonical"]


@pytest.mark.parametrize("profile", PROFILES)
def test_creep_is_labelled_creep(results, profile):
    r = results[profile]
    creeps = {c["canonical"] for c in r["gt"]["price_changes"] if c["kind"] == "creep"}
    for canonical in creeps:
        if canonical not in r["detected"]:
            continue
        kinds = {c.kind for c in r["detected"][canonical]["changes"]}
        assert kinds == {"creep"}, f"{profile}: {canonical} kinds={kinds}"


def test_llm_fallback_never_blocks_without_a_key(monkeypatch):
    """§2: every LLM step has a non-LLM fallback and never blocks the pipeline."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    normalize._LLM_CACHE.clear()
    assert normalize.llm_resolve(["SOME UNKNOWN MERCHANT"]) == {}

    txns, _ = load_profile(PROFILES[0])
    with_llm = normalize.cluster(txns, use_llm=True)
    without = normalize.cluster(txns, use_llm=False)
    assert {c.canonical for c in with_llm} == {c.canonical for c in without}


def test_llm_failure_does_not_change_detection(monkeypatch):
    """The case that actually matters at 4 AM: key present, Groq broken.

    Rate limit, deprecated model ID, truncated JSON — detection must be
    byte-identical to the no-LLM path, not merely non-crashing.
    """
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake_key_for_testing")
    normalize._LLM_CACHE.clear()

    class ExplodingGroq:
        def __init__(self, *a, **kw):
            raise RuntimeError("429 rate_limit_exceeded")

    monkeypatch.setitem(sys.modules, "groq", type(sys)("groq"))
    sys.modules["groq"].Groq = ExplodingGroq

    assert normalize.llm_resolve(["TOTALLY UNKNOWN MERCHANT"]) == {}

    txns, gt = load_profile(PROFILES[0])
    detected, _, _ = run_engine(txns)
    truth = {s["canonical"] for s in gt["subscriptions"]}
    assert prf(set(detected), truth)["recall"] == 1.0


def test_normalization_collapses_the_four_netflix_strings():
    """Slide 3: four raw strings, one subscription."""
    raws = [
        "UPI/NETFLIX BILLDESK/928471/PAYMENT",
        "ACH-D- NETFLIX ENTERTAINMENT SERVICES",
        "NEFT-NETFLIXENT-8821-RTGS",
        "POS 4471XXXX2210 NETFLIX.COM MUMBAI",
    ]
    assert {normalize.resolve(r)[0] for r in raws} == {"Netflix"}
