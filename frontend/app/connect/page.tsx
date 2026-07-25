"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, ingestCsv } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Analysis } from "@/lib/types";

const API = process.env.NEXT_PUBLIC_API_URL;

export default function Connect() {
  const router = useRouter();
  const { setAnalysis, reset } = useSession();
  const [api, setApi] = useState<"checking" | "waking" | "up" | "down">("checking");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // This ping doubles as the wake-up call: Render's free tier sleeps after
  // ~15 minutes and takes ~50s to come back, so firing it the moment someone
  // opens this page means the service is usually warm by the time they pick a
  // file. Say "waking up" rather than leaving a dead dot for a minute.
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

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const analysis: Analysis = await ingestCsv(file);
      reset();
      setAnalysis(analysis);
      router.push("/scanning");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't read that file.");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 pb-24 pt-10 sm:px-8">
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
        Upload your statement.
      </h1>
      <p className="mt-4 max-w-2xl leading-relaxed text-muted">
        Export the last 12–18 months as CSV from your bank&rsquo;s net banking.
        The longer the window, the more Sieve can see — annual subscriptions and
        slow price creep only show up over time.
      </p>

      {error && (
        <p
          role="alert"
          className="mt-8 rounded-sm border border-cancel/50 bg-cancel/10 px-4 py-3 text-sm text-ink"
        >
          {error}
        </p>
      )}

      <section className="mt-10 rounded-sm border border-line bg-surface p-6">
        <h2 className="text-sm font-medium text-ink">Before you upload</h2>
        <ul className="mt-4 space-y-2 border-t border-line pt-4">
          <li className="text-xs leading-relaxed text-faint">
            Your file is parsed for this one request and discarded. Nothing is
            written to a database, because there isn&rsquo;t one.
          </li>
          <li className="text-xs leading-relaxed text-faint">
            Column names are matched loosely, so differences between banks still
            work — including the separate withdrawal and deposit columns HDFC
            and ICICI export.
          </li>
          <li className="text-xs leading-relaxed text-faint">
            Nothing is sent anywhere else, and no account number leaves the
            analysis.
          </li>
        </ul>

        <div className="mt-6 flex flex-wrap items-center gap-4">
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload(file);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
            className="rounded-sm bg-brass px-5 py-3 text-sm font-medium text-ground transition-colors hover:bg-ink disabled:cursor-not-allowed disabled:bg-line disabled:text-faint"
          >
            {busy ? "Reading your statement…" : "Choose a CSV file"}
          </button>
          <a
            href="/samples/sample-statement.csv"
            download
            className="text-xs text-brass underline underline-offset-4 hover:text-ink"
          >
            Download a sample statement
          </a>
        </div>

        <p className="mt-5 text-xs leading-relaxed text-faint">
          Expected columns: a date, a description, and either an amount with a
          Dr/Cr marker or separate withdrawal and deposit columns. Exact names
          don&rsquo;t matter.
        </p>
      </section>

      <p className="mt-8 text-xs leading-relaxed text-faint">
        No account, no OAuth, no permissions to grant. If you&rsquo;d rather not
        upload anything,{" "}
        <Link href="/" className="text-brass underline underline-offset-4">
          the sample data
        </Link>{" "}
        shows exactly the same analysis.
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
