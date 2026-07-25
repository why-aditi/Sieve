"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { count, money, scanDay } from "@/lib/format";
import { useSession } from "@/lib/session";

const STAGGER_MS = 34;
const SOURCE_LABEL: Record<string, string> = {
  demo: "sample",
  csv: "statement",
};

export default function Scanning() {
  const router = useRouter();
  const { analysis } = useSession();
  const [shown, setShown] = useState(0);

  // In-memory session only: a refresh here has nothing to show.
  useEffect(() => {
    if (!analysis) router.replace("/");
  }, [analysis, router]);

  const stream = analysis?.stream ?? [];

  useEffect(() => {
    if (!stream.length) return;
    // Reveal is paced for reading, not to simulate work — the analysis was
    // already complete before this screen mounted. The receipt below is the
    // real count, not a running tally we invented.
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return setShown(stream.length);

    const id = setInterval(
      () => setShown((n) => (n >= stream.length ? (clearInterval(id), n) : n + 1)),
      STAGGER_MS,
    );
    return () => clearInterval(id);
  }, [stream.length]);

  if (!analysis) return null;

  const done = shown >= stream.length;
  const r = analysis.receipt;
  const visible = stream.slice(0, shown);

  return (
    <main className="mx-auto max-w-3xl px-6 pb-24 pt-10 sm:px-8">
      <header className="flex items-baseline justify-between">
        <span className="font-mono text-sm text-ink">sieve</span>
        <span className="text-xs text-faint">
          {done ? "Scan complete" : "Reading rows…"}
        </span>
      </header>

      <h1 className="mt-14 text-2xl tracking-tight text-ink sm:text-3xl">
        {done ? "Here's what we read." : "Reading your statement."}
      </h1>

      <div
        className="mt-8 h-px w-full bg-line"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={stream.length}
        aria-valuenow={shown}
      >
        <div
          className="h-px bg-brass transition-[width] duration-100"
          style={{ width: `${(shown / Math.max(1, stream.length)) * 100}%` }}
        />
      </div>

      <ul className="mt-6 space-y-0.5">
        {visible.map((t, i) => (
          <li
            key={`${t.date}-${t.merchant_raw}-${i}`}
            className="anim-in grid grid-cols-[auto_1fr_auto] items-center gap-3 py-1.5 text-xs"
          >
            <span className="tnum w-14 shrink-0 text-faint">{scanDay(t.date)}</span>
            <span
              className={`truncate font-mono ${t.matched ? "text-ink" : "text-faint"}`}
              title={t.merchant_raw}
            >
              {t.merchant_raw}
            </span>
            <span className="flex items-center gap-2 justify-self-end">
              {t.matched && (
                <span className="rounded-sm border border-brassdim px-1.5 py-0.5 text-[10px] text-brass">
                  {t.matched}
                </span>
              )}
              <span className="text-[10px] uppercase tracking-wide text-faint">
                {SOURCE_LABEL[t.source] ?? t.source}
              </span>
              <span className="tnum w-16 text-right text-muted">
                {money(t.amount)}
              </span>
            </span>
          </li>
        ))}
      </ul>

      {done && r && (
        <section className="anim-settle mt-12 rounded-sm border border-line bg-surface p-6">
          <h2 className="text-xs uppercase tracking-wider text-faint">
            What we read
          </h2>
          <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            {[
              ["Rows read", count(r.scanned)],
              ["Transactions found", count(r.matched)],
              ["Unreadable", count(r.unparsed)],
              ["Attachments opened", String(r.attachments_opened)],
              ["Bytes stored", String(r.bytes_stored)],
              ["Sent anywhere else", "0"],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-[11px] text-faint">{label}</dt>
                <dd className="tnum mt-0.5 text-lg text-ink">{value}</dd>
              </div>
            ))}
          </dl>
          {r.notes.length > 0 && (
            <ul className="mt-5 space-y-1 border-t border-line pt-4">
              {r.notes.map((n) => (
                <li key={n} className="text-[11px] leading-relaxed text-faint">
                  {n}
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            onClick={() => router.push("/dashboard")}
            className="mt-6 rounded-sm bg-brass px-5 py-3 text-sm font-medium text-ground transition-colors hover:bg-ink"
          >
            See what we found →
          </button>
        </section>
      )}
    </main>
  );
}
