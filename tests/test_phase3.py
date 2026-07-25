"""Phase 3 — scoring (§11), dormancy (§10), actions (§12), /analyze.

Run with -s to see the per-profile action table that feeds slide 5.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import actions  # noqa: E402
import scoring  # noqa: E402
from main import DEMO_PROFILES, analyze  # noqa: E402
from models import Transaction  # noqa: E402


def load(profile: str) -> list[Transaction]:
    raw = json.loads(
        (ROOT / "data" / profile / "transactions.json").read_text("utf-8"))
    return [Transaction(**{**r, "date": date.fromisoformat(r["date"])}) for r in raw]


@pytest.fixture(scope="module")
def analyses():
    return {p: analyze(load(p)) for p in DEMO_PROFILES}


# ------------------------------------------------------------------- scoring


def test_breakdown_sums_to_the_score(analyses):
    """The 'why this score' bars must add up to the number beside them."""
    for profile, result in analyses.items():
        for s in result["subscriptions"]:
            total = sum(s["score_breakdown"].values())
            assert total == pytest.approx(s["leak_score"], abs=0.05), \
                f"{profile}/{s['canonical']}: bars {total} vs score {s['leak_score']}"


def test_score_and_band_bounds(analyses):
    for result in analyses.values():
        for s in result["subscriptions"]:
            assert 0.0 <= s["leak_score"] <= 100.0
            assert s["band"] in ("keep", "review", "downgrade", "cancel")
            assert scoring.band(s["leak_score"]) == s["band"]


def test_weights_match_the_spec():
    assert scoring.WEIGHTS == {
        "cost": 0.35, "dormancy": 0.25, "redundancy": 0.20,
        "unnoticed_hike": 0.15, "cheaper_tier": 0.05,
    }
    assert sum(scoring.WEIGHTS.values()) == pytest.approx(1.0)


def test_all_four_bands_are_reachable():
    """Regression on the §11 correction: dividing by total spend caps the score
    near 75 and makes 'Cancel' impossible. Dividing by the largest sub fixes it."""
    top, _ = scoring.leak_score(
        annual_cost=24000, max_annual_cost=24000, dormancy=1.0,
        is_redundant=True, has_unnoticed_hike=True, has_cheaper_tier=True)
    assert top == pytest.approx(100.0)
    assert scoring.band(top) == "cancel"

    floor, _ = scoring.leak_score(1200, 24000, 0.0, False, False, False)
    assert scoring.band(floor) == "keep"


def test_redundancy_is_not_double_counted(analyses):
    """One fact, one bar. Redundancy has its own 0.20 term and must not also
    inflate the 0.25 dormancy term."""
    for result in analyses.values():
        for s in result["subscriptions"]:
            if not s["redundant_with"]:
                continue
            others = [t for t in s["dormancy_signals"]
                      if not t.startswith("Duplicate ")]
            # Dormancy points must be explainable by the non-redundancy signals
            # alone; with none present the dormancy term must be zero.
            if not others:
                assert s["score_breakdown"]["dormancy"] == 0.0, s["canonical"]


def test_portfolio_score_is_spend_weighted(analyses):
    for result in analyses.values():
        subs = result["subscriptions"]
        if not subs:
            continue
        expected = scoring.portfolio_score(
            [(s["leak_score"], s["annual_cost"]) for s in subs])
        assert result["portfolio"]["portfolio_leak_score"] == expected
        assert min(s["leak_score"] for s in subs) - 0.1 <= expected
        assert expected <= max(s["leak_score"] for s in subs) + 0.1


# ------------------------------------------------------------------ dormancy


def test_every_inferred_signal_is_labelled_a_proxy(analyses):
    """§10: we cannot see usage. Inference must never read as measurement."""
    honest_prefixes = ("Proxy: ", "You said ", "You confirmed ", "Duplicate ")
    for result in analyses.values():
        for s in result["subscriptions"]:
            for sig in s["dormancy_signals"]:
                assert sig.startswith(honest_prefixes), sig


def test_trial_conversion_is_a_dormancy_signal(analyses):
    for profile, result in analyses.items():
        gt = json.loads(
            (ROOT / "data" / profile / "ground_truth.json").read_text("utf-8"))
        for trial in gt["trial_conversions"]:
            sub = next(s for s in result["subscriptions"]
                       if s["canonical"] == trial["canonical"])
            assert any("trial" in sig for sig in sub["dormancy_signals"]), \
                f"{profile}/{trial['canonical']}: {sub['dormancy_signals']}"


def test_forgotten_annual_is_flagged(analyses):
    for profile, result in analyses.items():
        gt = json.loads(
            (ROOT / "data" / profile / "ground_truth.json").read_text("utf-8"))
        for canonical in gt["forgotten_annual"]:
            sub = next(s for s in result["subscriptions"]
                       if s["canonical"] == canonical)
            assert any("renewed silently" in sig for sig in sub["dormancy_signals"])


def test_usage_tap_yes_overrides_every_proxy():
    """The user knows whether they use it; our proxies do not get to argue."""
    txns = load("student")
    base = analyze(txns)
    trial = next(s for s in base["subscriptions"] if s["canonical"] == "ChatGPT Plus")
    assert trial["score_breakdown"]["dormancy"] > 0

    tapped = analyze(txns, {"ChatGPT Plus": "yes"})
    after = next(s for s in tapped["subscriptions"] if s["canonical"] == "ChatGPT Plus")
    assert after["score_breakdown"]["dormancy"] == 0.0
    assert after["leak_score"] < trial["leak_score"]


def test_unsure_is_a_real_signal_between_yes_and_no():
    txns = load("young_professional")
    scores = {}
    for tap in ("yes", "unsure", "no"):
        result = analyze(txns, {"Netflix": tap})
        scores[tap] = next(s for s in result["subscriptions"]
                           if s["canonical"] == "Netflix")["leak_score"]
    assert scores["yes"] < scores["unsure"] < scores["no"], scores


# ------------------------------------------------------------------- actions


def test_every_subscription_gets_an_actionable_action(analyses):
    for result in analyses.values():
        for s in result["subscriptions"]:
            a = s["action"]
            assert a["kind"] in ("cancel", "downgrade", "renegotiate", "keep")
            assert a["label"]
            assert a["est_annual_saving"] >= 0
            if a["kind"] != "keep":
                assert a["menu_path"], f"{s['canonical']} has no menu path"


def test_savings_are_computed_not_invented(analyses):
    """Every rupee in the headline must be traceable to an arithmetic rule."""
    for result in analyses.values():
        for s in result["subscriptions"]:
            a, saving = s["action"], s["action"]["est_annual_saving"]
            if a["kind"] == "cancel":
                assert saving == pytest.approx(s["annual_cost"])
            elif a["kind"] == "downgrade":
                tier = s["cheaper_tier"]
                assert tier is not None
                assert saving <= s["annual_cost"]
            elif a["kind"] == "renegotiate":
                # Only the hike we can prove is claimable.
                assert saving <= s["annual_cost"]
            else:
                assert saving == 0.0


def test_top_20_lookup_table_is_populated():
    assert len(actions.MERCHANTS) >= 20
    for name, m in actions.MERCHANTS.items():
        assert m.url.startswith("https://"), name
        assert ">" in m.menu_path, f"{name}: menu path must be a real path"
        assert m.tiers, name


def test_cheaper_tier_picks_the_next_one_down():
    assert actions.cheaper_tier("Netflix", 649) == ("Basic", 499)
    assert actions.cheaper_tier("Netflix", 199) is None      # already cheapest
    assert actions.cheaper_tier("Unknown Merchant", 500) is None


def test_renegotiation_email_falls_back_without_a_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    actions._EMAIL_CACHE.clear()
    draft = actions.renegotiation_email("Cult.fit", "fitness", 1888, 1499, "monthly")
    assert "Subject:" in draft and "Cult.fit" in draft
    assert "1,888" in draft and "1,499" in draft


def test_renegotiation_email_survives_a_broken_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    actions._EMAIL_CACHE.clear()
    monkeypatch.setitem(sys.modules, "groq", type(sys)("groq"))

    def explode(*a, **kw):
        raise RuntimeError("503 service_unavailable")
    sys.modules["groq"].Groq = explode

    draft = actions.renegotiation_email("Airtel", "telecom", 999, 999, "monthly")
    assert "Subject:" in draft and "Airtel" in draft


# ----------------------------------------------------------------- statelessness


def test_analysis_is_pure(analyses):
    """Same input, same output — nothing is stored between calls (§16)."""
    txns = load("family")
    assert analyze(txns) == analyze(txns)


def test_excluded_panel_groups_by_class_not_raw_string(analyses):
    """§8.1's claim is '6 recurring payments correctly excluded' — six classes.

    Per-cluster rows double-count any obligation whose two bank templates clean
    to strings too different to fuzzy-merge, which inflates the count on the one
    panel whose whole value is being right.
    """
    for profile, result in analyses.items():
        groups = result["excluded"]
        assert groups, "the correctly-excluded panel needs content"
        reasons = [g["reason"] for g in groups]
        assert len(reasons) == len(set(reasons)), f"{profile}: duplicate rows"
        assert set(reasons) == {"rent", "salary", "emi", "sip", "cc_bill", "utility"}
        for g in groups:
            assert g["label"] and g["merchants"] and g["approx_monthly"] > 0
            assert g["occurrences"] == sum(m["occurrences"] for m in g["merchants"])


def test_maharashtra_electricity_board_is_not_a_streaming_service():
    """Regression: substring alias matching resolved M-AHA-DISCOM to 'Aha'."""
    import normalize
    canonical, category, _ = normalize.resolve("UPI/MAHADISCOM/177550/PAYMENT")
    assert canonical != "Aha" and category != "streaming"
    # The boundary rule must not break glued brand tokens.
    assert normalize.resolve("NEFT-NETFLIXENT-8821-RTGS")[0] == "Netflix"
    assert normalize.resolve("UPI/SPOTIFYINDIA/512873/PAYMENT")[0] == "Spotify"
    assert normalize.resolve("NEFT-CULTFITIND-1321-RTGS")[0] == "Cult.fit"


def test_cancel_band_appears_when_the_user_taps_no():
    """The tap is what surfaces the strongest recommendation (§10).

    Nothing in the corpus trips all five scoring signals unaided, so 'Cancel'
    only appears once the judge answers 'have you used it?' — which is exactly
    the interaction §10 adds it for.
    """
    txns = load("student")
    before = next(s for s in analyze(txns)["subscriptions"]
                  if s["canonical"] == "ChatGPT Plus")
    assert before["band"] == "downgrade"

    after = next(s for s in analyze(txns, {"ChatGPT Plus": "no"})["subscriptions"]
                 if s["canonical"] == "ChatGPT Plus")
    assert after["band"] == "cancel"
    assert after["action"]["kind"] == "cancel"
    assert after["action"]["est_annual_saving"] == pytest.approx(after["annual_cost"])


# ---------------------------------------------------------------------- report


def test_action_plan_report(analyses, capsys):
    lines = ["", "=" * 78, "SIEVE — ACTION PLAN (§11 scoring, §12 actions)", "=" * 78]
    for profile, result in analyses.items():
        p = result["portfolio"]
        lines += [
            "", f"── {profile} " + "─" * (74 - len(profile)),
            f"  Rs {p['monthly_leak']:,.0f}/month leaking · portfolio score "
            f"{p['portfolio_leak_score']} · {p['subscription_count']} subs · "
            f"{p['excluded_count']} correctly excluded",
            f"  ACT ON ALL  ->  SAVE Rs {p['annual_savings_if_actioned']:,.0f}/YEAR",
            "",
            f"  {'merchant':<16}{'score':>6} {'band':<10}{'action':<13}"
            f"{'Rs saved/yr':>12}",
        ]
        for s in result["subscriptions"]:
            lines.append(
                f"  {s['canonical']:<16}{s['leak_score']:>6.1f} {s['band']:<10}"
                f"{s['action']['kind']:<13}{s['action']['est_annual_saving']:>12,.0f}")
        bands = {s["band"] for s in result["subscriptions"]}
        lines.append(f"  bands present: {', '.join(sorted(bands))}")
    lines += ["=" * 78, ""]
    with capsys.disabled():
        print("\n".join(lines))
