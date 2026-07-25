"""Build the bundles the frontend ships (§6.2, non-negotiable #3).

Not fetched at runtime: the demo path must make zero network calls, and Render's
free tier cold-starts at ~50s. Everything here is real adapter output over the
real corpus — no field is synthesised.

    python export_demo.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import exclusions
import normalize
from adapters import DEMO_PROFILES, GmailAdapter, SmsPasteAdapter
from dedup import dedup
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


def build(profile: str) -> tuple[dict, dict]:
    sms_text = (DATA / profile / "sms.txt").read_text(encoding="utf-8")
    emails = json.loads((DATA / profile / "emails.json").read_text(encoding="utf-8"))

    sms = SmsPasteAdapter().fetch(sms_text, use_llm=False)
    mail = GmailAdapter().fetch(emails, use_llm=False)

    # --- SMS-only bundle (the landing page's primary demo) ---------------
    sms_receipt = {**vars(sms.receipt), "summary": sms.receipt.summary(), "notes": [
        "Sample inbox: 18 months of bank SMS, read by the same parser a real paste uses",
        "No network call, no credentials, no upload",
    ]}
    sms_bundle = {"profile": profile, "receipt": sms_receipt, **analyze(sms.transactions)}
    sms_bundle["stream"] = stream_sample(
        sms.transactions, {s["canonical"] for s in sms_bundle["subscriptions"]})

    # --- Combined bundle: SMS + email receipts, deduped (§6.7) -----------
    merged, report = dedup(sms.transactions + mail.transactions)
    combined = analyze(merged)
    combined_receipt = {
        "source": "gmail+sms_paste",
        "scanned": sms.receipt.scanned + mail.receipt.scanned,
        "matched": len(merged),
        "ignored": sms.receipt.ignored + mail.receipt.ignored,
        "unparsed": sms.receipt.unparsed + mail.receipt.unparsed,
        "llm_recovered": 0,
        "attachments_opened": 0,
        "bytes_stored": 0,
        "notes": [
            f"{len(sms.transactions)} bank SMS and {len(mail.transactions)} email "
            f"receipts describe the same account",
            f"{report.merged} charges arrived from both sources and were merged into one",
            "Read the plain-text body only — no attachment was opened",
        ],
    }
    combined_receipt["summary"] = (
        f"Scanned {combined_receipt['scanned']:,} · "
        f"{combined_receipt['ignored']:,} ignored · "
        f"{len(merged):,} transactions found · "
        f"{report.merged:,} duplicates merged · "
        f"0 attachments opened · 0 bytes stored"
    )
    combined_bundle = {"profile": profile, "receipt": combined_receipt, **combined}
    combined_bundle["stream"] = stream_sample(
        merged, {s["canonical"] for s in combined["subscriptions"]})

    return sms_bundle, combined_bundle


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for profile in DEMO_PROFILES:
        sms_bundle, combined_bundle = build(profile)
        for name, bundle in ((profile, sms_bundle), (f"{profile}_combined", combined_bundle)):
            path = OUT / f"{name}.json"
            path.write_text(
                json.dumps(bundle, cls=DateEncoder, separators=(",", ":")),
                encoding="utf-8",
            )
            r = bundle["receipt"]
            print(
                f"{name:32s} {path.stat().st_size / 1024:6.1f}KB  "
                f"scanned={r['scanned']:,} found={r['matched']:,} "
                f"subs={len(bundle['subscriptions'])}"
            )


if __name__ == "__main__":
    main()
