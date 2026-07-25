"""Build the bundles the frontend ships (§6.2, non-negotiable #3).

Not fetched at runtime: the demo path must make zero network calls, and Render's
free tier cold-starts at ~50s. Everything here is real adapter output over the
real corpus — the demo parses the same statement.csv a user would upload.

    python export_demo.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import exclusions
import normalize
from adapters import DEMO_PROFILES, CsvAdapter
from main import analyze

DATA = Path(__file__).resolve().parents[1] / "data"
OUT = Path(__file__).resolve().parents[1] / "frontend" / "lib" / "data"
STREAM_SIZE = 54


class DateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, date):
            return o.isoformat()
        return super().default(o)


def stream_sample(txns, subs: set[str]) -> list[dict]:
    """A real, evenly-spread sample of what was read — nothing reconstructed."""
    kept, _ = exclusions.split(normalize.cluster(txns))
    label = {r: c.canonical for c in kept if c.canonical in subs for r in c.raw_variants}
    ordered = sorted(txns, key=lambda t: t.date)
    step = max(1, len(ordered) // STREAM_SIZE)
    return [
        {"date": t.date, "merchant_raw": t.merchant_raw, "amount": t.amount,
         "source": t.source, "matched": label.get(t.merchant_raw)}
        for t in ordered[::step]
    ][:STREAM_SIZE]


def build(profile: str) -> dict:
    csv = (DATA / profile / "statement.csv").read_bytes()
    result = CsvAdapter().fetch(csv)

    receipt = {**vars(result.receipt), "notes": [
        f"Sample statement: 18 months of one account, {result.receipt.matched:,} rows",
        "Read with the same parser a real upload uses — no network call, no upload",
    ]}
    receipt["summary"] = result.receipt.summary()

    bundle = {"profile": profile, "receipt": receipt, **analyze(result.transactions)}
    bundle["stream"] = stream_sample(
        result.transactions, {s["canonical"] for s in bundle["subscriptions"]})
    return bundle


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for profile in DEMO_PROFILES:
        bundle = build(profile)
        path = OUT / f"{profile}.json"
        path.write_text(
            json.dumps(bundle, cls=DateEncoder, separators=(",", ":")),
            encoding="utf-8",
        )
        p = bundle["portfolio"]
        print(
            f"{profile:22s} {path.stat().st_size / 1024:6.1f}KB  "
            f"rows={bundle['receipt']['scanned']:,} subs={p['subscription_count']} "
            f"leak=Rs{p['monthly_leak']:,.0f}/mo"
        )


if __name__ == "__main__":
    main()
