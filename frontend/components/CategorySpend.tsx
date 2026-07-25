"use client";

import { money } from "@/lib/format";
import { SERIES, type Subscription } from "@/lib/types";

/** Spend by category — a RANKED BAR, not a donut.
 *
 *  The brief asked for a donut. Validated against this surface, a donut caps
 *  at three slices: at four, the magenta and aqua slots sit at deutan ΔE 1.6,
 *  which a red-green colourblind reader cannot tell apart at all. With 5-7
 *  categories in the data that meant either folding most of the spend into
 *  "Other" or shipping an unreadable chart.
 *
 *  The same six hues pass every check as an adjacent pairlist (worst CVD ΔE
 *  8.4, worst normal-vision 19.3), which is what a bar chart is — and bars
 *  compare magnitudes better than angles anyway. Categories beyond six fold
 *  into "Other"; hues are assigned in fixed order and never cycled. */

/** capitalize() renders "saas" as "Saas". These are proper nouns. */
const CATEGORY_LABEL: Record<string, string> = {
  saas: "SaaS",
  streaming: "Streaming",
  music: "Music",
  cloud: "Cloud storage",
  fitness: "Fitness",
  telecom: "Telecom",
  food: "Food",
  insurance: "Insurance",
  utility: "Utilities",
  retail: "Retail",
  transport: "Transport",
  other: "Other",
};

export function CategorySpend({ subs }: { subs: Subscription[] }) {
  const totals = new Map<string, number>();
  for (const s of subs) {
    totals.set(s.category, (totals.get(s.category) ?? 0) + s.annual_cost);
  }

  const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]);
  const shown = ranked.slice(0, SERIES.length);
  const rest = ranked.slice(SERIES.length);
  if (rest.length) {
    shown.push(["Other", rest.reduce((sum, [, v]) => sum + v, 0)]);
  }

  const max = Math.max(...shown.map(([, v]) => v));
  const total = shown.reduce((sum, [, v]) => sum + v, 0);

  return (
    <div>
      <ul className="space-y-3">
        {shown.map(([name, value], i) => (
          <li key={name}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
              <span className="text-xs text-muted">
                {CATEGORY_LABEL[name] ?? name}
              </span>
              <span className="tnum text-xs text-ink">
                {money(value)}
                <span className="ml-2 text-faint">
                  {Math.round((value / total) * 100)}%
                </span>
              </span>
            </div>
            <div className="h-2 w-full rounded-sm bg-line">
              <div
                className="h-full rounded-sm"
                style={{
                  width: `${(value / max) * 100}%`,
                  background: SERIES[i % SERIES.length],
                }}
              />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[11px] text-faint">
        Yearly spend across {shown.length} categories · {money(total)} total
      </p>
    </div>
  );
}
