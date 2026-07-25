"use client";

import { useState } from "react";
import { ScoreBars } from "@/components/ScoreBars";
import { Sparkline } from "@/components/Sparkline";
import { day, money, PERIOD_LABEL } from "@/lib/format";
import { BAND_COLOR, BAND_LABEL, type Subscription, type UsageTap } from "@/lib/types";

const TAPS: { value: UsageTap; label: string }[] = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
  { value: "unsure", label: "Can't remember" },
];

/** Distinct FORMATS, not distinct strings.
 *
 *  Every charge carries its own reference number, so Cult.fit has 11 unique
 *  raw strings but only 4 shapes. Counting strings would say "11 different
 *  descriptions" on the very screen that is supposed to prove the landing
 *  page's "your bank writes it four different ways". Mask the digit runs, and
 *  show a real example of each shape with how many charges wore it. */
function formats(variants: string[]) {
  const groups = new Map<string, { example: string; count: number }>();
  for (const v of variants) {
    const shape = v.replace(/\d{4,}/g, "#");
    const hit = groups.get(shape);
    if (hit) hit.count += 1;
    else groups.set(shape, { example: v, count: 1 });
  }
  return [...groups.values()].sort((a, b) => b.count - a.count);
}

/** The backend writes ASCII-safe labels; render them properly here. */
const pretty = (s: string) =>
  s.replace(/Rs (?=[\d,])/g, "₹").replace(/\s->\s/g, " → ");

export function SubscriptionRow({
  sub,
  tap,
  onTap,
}: {
  sub: Subscription;
  tap: UsageTap | undefined;
  onTap: (t: UsageTap | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const panelId = `panel-${sub.canonical.replace(/\W/g, "")}`;
  const shapes = formats(sub.raw_variants);

  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-4 py-4 text-left transition-colors hover:bg-surface sm:grid-cols-[1.6fr_1fr_1fr_auto_auto] sm:gap-x-6"
      >
        <span className="flex items-center gap-2 min-w-0">
          <span
            aria-hidden
            className="text-xs text-faint transition-transform"
            style={{ transform: open ? "rotate(90deg)" : "none" }}
          >
            ▸
          </span>
          <span className="truncate font-medium text-ink">{sub.canonical}</span>
        </span>

        <span className="tnum text-right text-sm text-ink sm:text-left">
          {money(sub.current_amount)}
          <span className="ml-1.5 text-xs text-faint">
            {PERIOD_LABEL[sub.period]}
          </span>
        </span>

        <span className="hidden text-xs text-muted sm:block">
          next {day(sub.next_charge_date)}
        </span>

        <span className="tnum hidden text-right text-sm text-ink sm:block">
          {sub.leak_score.toFixed(0)}
        </span>

        {/* Status colour never travels alone — the band name is always beside it. */}
        <span className="flex items-center justify-end gap-2">
          <span
            aria-hidden
            className="h-2 w-2 rounded-full"
            style={{ background: BAND_COLOR[sub.band] }}
          />
          <span className="text-xs uppercase tracking-wide text-muted">
            {BAND_LABEL[sub.band]}
          </span>
        </span>
      </button>

      {open && (
        <div
          id={panelId}
          className="grid gap-8 bg-raised px-4 py-6 sm:grid-cols-2 sm:px-10"
        >
          <section>
            <h4 className="mb-3 text-xs uppercase tracking-wider text-faint">
              Why this score
            </h4>
            <ScoreBars breakdown={sub.score_breakdown} score={sub.leak_score} />
            {sub.dormancy_signals.length > 0 && (
              <ul className="mt-4 space-y-1.5 text-xs text-muted">
                {sub.dormancy_signals.map((s) => (
                  <li key={s} className="leading-relaxed">
                    {s}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h4 className="mb-3 text-xs uppercase tracking-wider text-faint">
              What you paid
            </h4>
            <Sparkline
              points={sub.price_history}
              changeDates={sub.price_changes.map((c) => c.changed_on)}
            />

            <h4 className="mb-2 mt-6 text-xs uppercase tracking-wider text-faint">
              We matched {shapes.length} different format
              {shapes.length === 1 ? "" : "s"}
              <span className="ml-1 normal-case tracking-normal">
                ({sub.raw_variants.length} charges)
              </span>
            </h4>
            <ul className="space-y-1">
              {shapes.map((s) => (
                <li
                  key={s.example}
                  className="flex items-baseline gap-2 font-mono text-[11px] text-faint"
                >
                  <span className="truncate" title={s.example}>
                    {s.example}
                  </span>
                  {s.count > 1 && (
                    <span className="ml-auto shrink-0 text-brassdim">
                      ×{s.count}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>

          <section className="sm:col-span-2">
            <h4 className="mb-3 text-xs uppercase tracking-wider text-faint">
              Used it this month?
            </h4>
            <div className="flex flex-wrap gap-2">
              {TAPS.map((t) => {
                const active = tap === t.value;
                return (
                  <button
                    key={t.value}
                    type="button"
                    aria-pressed={active}
                    onClick={() => onTap(active ? null : t.value)}
                    className={`rounded-sm border px-3 py-1.5 text-xs transition-colors ${
                      active
                        ? "border-brass bg-brass/10 text-brass"
                        : "border-line text-muted hover:border-brassdim hover:text-ink"
                    }`}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>
          </section>

          <section className="sm:col-span-2 border-t border-line pt-5">
            <h4 className="mb-2 text-xs uppercase tracking-wider text-faint">
              What to do
            </h4>
            <p className="text-sm text-ink">{pretty(sub.action.label)}</p>
            {sub.action.est_annual_saving > 0 && (
              <p className="tnum mt-1 text-sm text-brass">
                saves {money(sub.action.est_annual_saving)} a year
              </p>
            )}
            {sub.action.menu_path && (
              <p className="mt-3 font-mono text-[11px] text-muted">
                {sub.action.menu_path}
              </p>
            )}
            {sub.action.url && (
              <a
                href={sub.action.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-block text-xs text-brass underline underline-offset-4 hover:text-ink"
              >
                Open the cancellation page ↗
              </a>
            )}
          </section>
        </div>
      )}
    </li>
  );
}
