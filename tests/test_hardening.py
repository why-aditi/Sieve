"""Pre-freeze hardening.

Two promises this file exists to keep:

  1. Every LLM call has a bounded cost and a non-LLM fallback (§2). With no
     API key, a broken client, or a hanging one, the pipeline still produces a
     complete dashboard.
  2. Malformed input produces a sentence a person can act on — never a stack
     trace, never a pydantic error blob.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import actions  # noqa: E402
import adapters  # noqa: E402
import config  # noqa: E402
import normalize  # noqa: E402
from adapters import CsvAdapter, DemoAdapter  # noqa: E402
from main import analyze, app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


# ------------------------------------------------------- 1. LLM containment


def test_llm_calls_are_time_bounded():
    """The SDK default is a 60s read timeout with 2 retries — up to ~3 minutes
    of hanging before the fallback runs, on a path a user is waiting on."""
    assert config.GROQ_TIMEOUT_SECONDS <= 10
    assert config.GROQ_MAX_RETRIES == 1


def test_every_groq_client_comes_from_the_one_factory():
    """A call site constructing Groq() directly would silently inherit the
    60s/2-retry defaults and escape the bound above."""
    import re
    for module in (normalize, actions):
        source = Path(module.__file__).read_text(encoding="utf-8")
        stray = re.findall(r"(?<!def )\bGroq\(", source)
        assert not stray, f"{Path(module.__file__).name} constructs Groq() directly"


def test_full_pipeline_with_no_api_key(monkeypatch):
    """The headline requirement: no key, complete dashboard."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    normalize._LLM_CACHE.clear()
    actions._EMAIL_CACHE.clear()

    result = analyze(DemoAdapter().fetch("young_professional").transactions)

    assert result["portfolio"]["subscription_count"] == 9
    assert result["portfolio"]["monthly_leak"] > 0
    assert result["portfolio"]["annual_savings_if_actioned"] > 0
    assert len(result["excluded"]) == 6
    for sub in result["subscriptions"]:
        assert sub["action"]["kind"] in ("cancel", "downgrade", "renegotiate", "keep")
        assert sum(sub["score_breakdown"].values()) == pytest.approx(sub["leak_score"], abs=0.05)

    # The renegotiation draft still arrives — from the static template.
    draft = actions.renegotiation_email("Cult.fit", "fitness", 1888, 1499, "monthly")
    assert "Subject:" in draft and "1,499" in draft


def test_pipeline_survives_a_hanging_llm(monkeypatch):
    """Key present, network wedged. Detection must be unchanged, not merely
    non-crashing."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    normalize._LLM_CACHE.clear()
    actions._EMAIL_CACHE.clear()

    def hang(*a, **kw):
        raise TimeoutError("read timeout")

    # Both remaining LLM call sites. The adapters carry none — CSV parsing is
    # entirely deterministic.
    monkeypatch.setattr(config, "groq_client", hang)
    monkeypatch.setattr(normalize, "groq_client", hang)
    monkeypatch.setattr(actions, "groq_client", hang)

    assert normalize.llm_resolve(["SOME UNKNOWN MERCHANT"]) == {}
    assert "Subject:" in actions.renegotiation_email("Airtel", "telecom", 999, 999, "monthly")

    result = analyze(DemoAdapter().fetch("student").transactions)
    assert result["portfolio"]["subscription_count"] == 8


# --------------------------------------------------- 2. malformed input


def detail(response) -> str:
    body = response.json()
    assert isinstance(body.get("detail"), str), f"detail must be a string: {body}"
    return body["detail"]


def test_random_text_file_as_csv():
    r = client.post("/ingest/csv", content=b"just some notes I had lying around")
    assert r.status_code == 422
    assert "date, a description and an amount" in detail(r)


def test_empty_csv():
    r = client.post("/ingest/csv", content=b"")
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


def test_headers_but_no_rows():
    r = client.post("/ingest/csv", content=b"Txn Date,Narration,Withdrawal Amt.\n")
    assert r.status_code == 422
    assert "no rows" in detail(r).lower()


def test_csv_with_wrong_headers():
    r = client.post("/ingest/csv", content=b"alpha,beta,gamma\n1,2,3\n4,5,6\n")
    assert r.status_code == 422
    msg = detail(r)
    assert "date, a description and an amount" in msg
    assert "alpha" in msg          # tells them what it actually saw


def test_binary_garbage_as_csv():
    r = client.post("/ingest/csv", content=bytes(range(256)) * 40)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


def test_no_stack_trace_ever_reaches_the_user():
    """A traceback in an error body is both ugly and an information leak."""
    probes = [
        ("/ingest/csv", {"content": b'"unclosed,,,\n\n\n'}),
        ("/ingest/csv", {"content": b""}),
        ("/ingest/csv", {"content": b"\xff\xfe\x00broken"}),
        ("/ingest/csv", {"content": bytes(range(256)) * 40}),
    ]
    for path, kwargs in probes:
        r = client.post(path, **kwargs)
        assert r.status_code in (413, 422, 500), f"{path} -> {r.status_code}"
        body = r.text
        for leak in ("Traceback", "File \"", "lxml", "pandas", ".py\", line"):
            assert leak not in body, f"{path} leaked {leak!r}: {body[:200]}"


def test_adapters_raise_valueerror_not_arbitrary_exceptions():
    """The endpoints translate ValueError into a 422; anything else becomes a
    500 with a generic message and loses the useful detail."""
    with pytest.raises(ValueError):
        CsvAdapter().fetch(b"a,b\n1,2\n")
    with pytest.raises(ValueError):
        CsvAdapter().fetch(b"\xff\xfe\x00 not a csv")


def test_demo_endpoint_rejects_unknown_profile_cleanly():
    r = client.get("/demo/../../etc/passwd")
    assert r.status_code == 404
    assert "Traceback" not in r.text


# ------------------------------------------------------- 3. cold start


def test_demo_needs_no_backend_at_all():
    """Non-negotiable #3. The frontend ships every demo bundle, so this is
    really a check that the bundles exist and are complete."""
    import json
    data = ROOT / "frontend" / "lib" / "data"
    for name in ("student", "young_professional", "family"):
        bundle = json.loads((data / f"{name}.json").read_text(encoding="utf-8"))
        assert bundle["subscriptions"], name
        assert bundle["portfolio"]["monthly_leak"] > 0, name
        assert bundle["receipt"]["summary"], name
        assert bundle["stream"], name
