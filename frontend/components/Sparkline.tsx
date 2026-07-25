"use client";

import { useId, useState } from "react";
import { money, shortDay } from "@/lib/format";

/** Price history. 2px line, ≥8px hover targets, and the points where the price
 *  actually changed marked — a flat line here is the story as much as a step is. */

const W = 320;
const H = 56;
const PAD = 6;

export function Sparkline({
  points,
  changeDates,
}: {
  points: { date: string; amount: number }[];
  changeDates: string[];
}) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return null;

  const amounts = points.map((p) => p.amount);
  const lo = Math.min(...amounts);
  const hi = Math.max(...amounts);
  const span = hi - lo || 1;

  const x = (i: number) => PAD + (i * (W - PAD * 2)) / (points.length - 1);
  const y = (v: number) => H - PAD - ((v - lo) / span) * (H - PAD * 2);

  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.amount)}`).join(" ");
  const changes = new Set(changeDates);
  const active = hover === null ? null : points[hover];

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ height: H }}
        role="img"
        aria-label={`Price history: ${money(points[0].amount)} in ${shortDay(
          points[0].date,
        )} to ${money(points[points.length - 1].amount)} in ${shortDay(
          points[points.length - 1].date,
        )}`}
        onMouseLeave={() => setHover(null)}
      >
        <path d={path} fill="none" stroke="var(--color-brass)" strokeWidth={2} />

        {points.map((p, i) =>
          changes.has(p.date) ? (
            <circle
              key={`${id}-c-${i}`}
              cx={x(i)}
              cy={y(p.amount)}
              r={4}
              fill="var(--color-downgrade)"
              stroke="var(--color-surface)"
              strokeWidth={2}
            />
          ) : null,
        )}

        {active && (
          <circle
            cx={x(hover!)}
            cy={y(active.amount)}
            r={4}
            fill="var(--color-ink)"
            stroke="var(--color-surface)"
            strokeWidth={2}
          />
        )}

        {/* Hit targets, wider than the marks. */}
        {points.map((p, i) => (
          <rect
            key={`${id}-h-${i}`}
            x={x(i) - 8}
            y={0}
            width={16}
            height={H}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>

      <div className="mt-1 flex justify-between text-[10px] text-faint">
        <span>{shortDay(points[0].date)}</span>
        <span aria-live="polite" className="tnum text-muted">
          {active ? `${shortDay(active.date)} · ${money(active.amount)}` : ""}
        </span>
        <span>{shortDay(points[points.length - 1].date)}</span>
      </div>
    </div>
  );
}
