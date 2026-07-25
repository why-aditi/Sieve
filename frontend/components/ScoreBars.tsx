"use client";

import { SCORE_TERM_LABEL, SERIES } from "@/lib/types";

/** "Why this score" — a stacked bar whose segments sum to the number printed
 *  beside it. §11's whole claim is that the score is arithmetic we display,
 *  so the bar is the arithmetic, not an illustration of it.
 *
 *  2px surface gaps between segments per the mark spec; the track is the full
 *  100 points so the unfilled remainder is visible rather than implied. */

const ORDER = ["cost", "dormancy", "redundancy", "unnoticed_hike", "cheaper_tier"];

export function ScoreBars({
  breakdown,
  score,
}: {
  breakdown: Record<string, number>;
  score: number;
}) {
  const terms = ORDER.filter((k) => (breakdown[k] ?? 0) > 0);

  return (
    <div>
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-sm bg-line"
        role="img"
        aria-label={`Leak score ${score} out of 100: ${terms
          .map((k) => `${SCORE_TERM_LABEL[k]} ${breakdown[k].toFixed(1)} points`)
          .join(", ")}`}
      >
        {terms.map((k, i) => (
          <div
            key={k}
            className="h-full"
            style={{
              width: `${breakdown[k]}%`,
              background: SERIES[i % SERIES.length],
              marginRight: i < terms.length - 1 ? 2 : 0,
            }}
          />
        ))}
      </div>

      <ul className="mt-3 space-y-1.5">
        {terms.map((k, i) => (
          <li key={k} className="flex items-center gap-2.5 text-xs">
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
              style={{ background: SERIES[i % SERIES.length] }}
            />
            <span className="text-muted">{SCORE_TERM_LABEL[k] ?? k}</span>
            <span className="tnum ml-auto text-ink">
              +{breakdown[k].toFixed(1)}
            </span>
          </li>
        ))}
        <li className="flex items-center gap-2.5 border-t border-line pt-1.5 text-xs">
          <span className="text-muted">Leak score</span>
          <span className="tnum ml-auto text-ink">{score.toFixed(1)} / 100</span>
        </li>
      </ul>
    </div>
  );
}
