"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, ingestCsv, ingestSms, ingestSmsXml } from "@/lib/api";
import { COMBINED, DEFAULT_PROFILE } from "@/lib/demo";
import { useSession } from "@/lib/session";
import type { Analysis } from "@/lib/types";

const API = process.env.NEXT_PUBLIC_API_URL;

export default function Connect() {
  const router = useRouter();
  const { setAnalysis, reset } = useSession();
  const [api, setApi] = useState<"checking" | "waking" | "up" | "down">("checking");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paste, setPaste] = useState("");
  const xmlInput = useRef<HTMLInputElement>(null);
  const csvInput = useRef<HTMLInputElement>(null);

  // The API only matters on this screen — the demo path never touches it.
  //
  // This ping doubles as the wake-up call: Render's free tier sleeps after
  // ~15 minutes and takes ~50s to come back, so firing it the moment someone
  // opens this page means the service is usually warm by the time they finish
  // pasting. Say "waking up" rather than leaving a dead dot for a minute.
  useEffect(() => {
    if (!API) return setApi("down");
    const slow = setTimeout(() => setApi((s) => (s === "checking" ? "waking" : s)), 2500);
    fetch(`${API}/health`)
      .then((r) => setApi(r.ok ? "up" : "down"))
      .catch(() => setApi("down"))
      .finally(() => clearTimeout(slow));
    return () => clearTimeout(slow);
  }, []);

  const apiLabel = {
    checking: "Checking service…",
    waking: "Waking the service — this takes about a minute on a free plan",
    up: "Service online",
    down: "Service unavailable — sample data still works",
  }[api];

  function land(analysis: Analysis) {
    reset();
    setAnalysis(analysis);
    router.push("/scanning");
  }

  async function run(label: string, work: () => Promise<Analysis>) {
    setBusy(label);
    setError(null);
    try {
      land(await work());
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Something went wrong reading that.",
      );
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 pb-24 pt-10 sm:px-8">
      <header className="flex items-baseline justify-between">
        <Link href="/" className="font-mono text-sm text-ink hover:text-brass">
          sieve
        </Link>
        <span className="flex items-center gap-2 text-xs text-faint">
          <span
            aria-hidden
            className="h-1.5 w-1.5 rounded-full"
            style={{
              background:
                api === "up" ? "var(--color-keep)"
                : api === "waking" ? "var(--color-review)"
                : "var(--color-faint)",
            }}
          />
          {apiLabel}
        </span>
      </header>

      <h1 className="mt-16 text-3xl tracking-tight text-ink sm:text-4xl">
        Choose what Sieve can see.
      </h1>
      <p className="mt-4 max-w-2xl leading-relaxed text-muted">
        Each of these works on its own. Grant one, grant all three, or grant
        none and look at the sample data instead.
      </p>

      {error && (
        <p
          role="alert"
          className="mt-8 rounded-sm border border-cancel/50 bg-cancel/10 px-4 py-3 text-sm text-ink"
        >
          {error}
        </p>
      )}

      <div className="mt-10 space-y-5">
        {/* ---------------------------------------------------------- Email */}
        <section className="rounded-sm border border-line bg-surface p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium text-ink">Email</h2>
            <span className="text-xs text-faint">Payment receipts</span>
          </div>
          <ul className="mt-4 space-y-1.5 border-t border-line pt-4">
            <li className="text-[11px] leading-relaxed text-faint">
              We read messages from 40 known bank and payment senders only.
            </li>
            <li className="text-[11px] leading-relaxed text-faint">
              We never open attachments — there is no code in Sieve that can.
            </li>
            <li className="text-[11px] leading-relaxed text-faint">
              No refresh token is ever stored, so access ends with this tab.
            </li>
          </ul>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled
              title="Gmail's read scope needs Google verification before strangers can use it"
              className="cursor-not-allowed rounded-sm border border-line px-4 py-2 text-xs text-faint"
            >
              Connect Google
            </button>
            <button
              type="button"
              onClick={() => land(COMBINED[DEFAULT_PROFILE])}
              className="rounded-sm bg-brass px-4 py-2 text-xs font-medium text-ground transition-colors hover:bg-ink"
            >
              Try with demo account
            </button>
            <span className="text-[11px] text-faint">
              Email receipts + bank SMS for one account, deduplicated
            </span>
          </div>
        </section>

        {/* ------------------------------------------------------------ SMS */}
        <section className="rounded-sm border border-line bg-surface p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium text-ink">SMS</h2>
            <span className="text-xs text-faint">The alerts already on your phone</span>
          </div>
          <ul className="mt-4 space-y-1.5 border-t border-line pt-4">
            <li className="text-[11px] leading-relaxed text-faint">
              A web page cannot read your SMS — no browser API exists for it. So
              you paste them, or upload an SMS Backup &amp; Restore export.
            </li>
            <li className="text-[11px] leading-relaxed text-faint">
              Messages are parsed for this request and discarded. Nothing is written down.
            </li>
          </ul>

          <label
            htmlFor="paste"
            className="mt-5 block text-xs text-muted"
          >
            Open Messages → filter to your bank → select all → copy → paste here
          </label>
          <textarea
            id="paste"
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            rows={5}
            spellCheck={false}
            placeholder="VM-HDFCBK: Rs.649.00 debited from a/c XX4471 on 14-03-26 to UPI/NETFLIX BILLDESK/928471/PAYMENT via NetBanking"
            className="mt-2 w-full resize-y rounded-sm border border-line bg-ground p-3 font-mono text-[11px] leading-relaxed text-ink placeholder:text-faint/60"
          />

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={!paste.trim() || busy !== null}
              onClick={() => run("paste", () => ingestSms(paste))}
              className="rounded-sm bg-brass px-4 py-2 text-xs font-medium text-ground transition-colors hover:bg-ink disabled:cursor-not-allowed disabled:bg-line disabled:text-faint"
            >
              {busy === "paste" ? "Reading…" : "Read these messages"}
            </button>

            <input
              ref={xmlInput}
              type="file"
              accept=".xml,text/xml,application/xml"
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) run("xml", () => ingestSmsXml(file));
                e.target.value = "";
              }}
            />
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => xmlInput.current?.click()}
              className="rounded-sm border border-line px-4 py-2 text-xs text-muted transition-colors hover:border-brassdim hover:text-ink disabled:cursor-not-allowed"
            >
              {busy === "xml" ? "Reading…" : "Upload XML export"}
            </button>

            <a
              href="/samples/sample-sms-backup.xml"
              download
              className="text-[11px] text-brass underline underline-offset-4 hover:text-ink"
            >
              Download a sample export
            </a>
          </div>
        </section>

        {/* ------------------------------------------------------ Statement */}
        <section className="rounded-sm border border-line bg-surface p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium text-ink">Statement</h2>
            <span className="text-xs text-faint">A CSV from net banking</span>
          </div>
          <ul className="mt-4 space-y-1.5 border-t border-line pt-4">
            <li className="text-[11px] leading-relaxed text-faint">
              Column names are matched loosely, so header differences between
              banks still work — including separate withdrawal and deposit columns.
            </li>
            <li className="text-[11px] leading-relaxed text-faint">
              The file is parsed for this request and discarded.
            </li>
          </ul>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <input
              ref={csvInput}
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) run("csv", () => ingestCsv(file));
                e.target.value = "";
              }}
            />
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => csvInput.current?.click()}
              className="rounded-sm bg-brass px-4 py-2 text-xs font-medium text-ground transition-colors hover:bg-ink disabled:cursor-not-allowed disabled:bg-line disabled:text-faint"
            >
              {busy === "csv" ? "Reading…" : "Upload CSV"}
            </button>
            <a
              href="/samples/sample-statement.csv"
              download
              className="text-[11px] text-brass underline underline-offset-4 hover:text-ink"
            >
              Download a sample statement
            </a>
          </div>
        </section>
      </div>

      <p className="mt-8 max-w-2xl text-xs leading-relaxed text-faint">
        Gmail&rsquo;s read scope needs Google verification before strangers can
        use it, so Connect Google is switched off rather than pretending to
        work. Everything the finished flow produces is in the demo account, on
        real parsing, with nothing faked downstream.
      </p>

      <Link
        href="/"
        className="mt-10 inline-block text-sm text-muted underline underline-offset-4 hover:text-ink"
      >
        ← Back
      </Link>
    </main>
  );
}
