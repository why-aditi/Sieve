"use client";

import { day, money, pct } from "@/lib/format";
import type { ExcludedGroup, Subscription } from "@/lib/types";

/** §9: "three hikes of 8% each over eighteen months is a different and more
 *  irritating story than one big jump." Listing a creep's three steps as three
 *  rows buries exactly the story the spec wants told — so a creep collapses
 *  into one entry carrying its cumulative move. */
function hikeStories(subs: Subscription[]) {
  const out: {
    merchant: string;
    from: number;
    to: number;
    pct: number;
    annual: number;
    when: string;
    steps: number;
    kind: "step" | "creep";
  }[] = [];

  for (const s of subs) {
    if (!s.price_changes.length) continue;
    const creeps = s.price_changes.filter((c) => c.kind === "creep");
    const steps = s.price_changes.filter((c) => c.kind === "step");

    if (creeps.length) {
      const first = creeps[0];
      const last = creeps[creeps.length - 1];
      out.push({
        merchant: s.canonical,
        from: first.from_amount,
        to: last.to_amount,
        pct: (last.to_amount / first.from_amount - 1) * 100,
        annual: last.annual_impact,
        when: last.changed_on,
        steps: creeps.length,
        kind: "creep",
      });
    }
    for (const c of steps) {
      out.push({
        merchant: s.canonical,
        from: c.from_amount,
        to: c.to_amount,
        pct: c.pct,
        annual: c.annual_impact,
        when: c.changed_on,
        steps: 1,
        kind: "step",
      });
    }
  }
  return out.sort((a, b) => b.annual - a.annual);
}

export function HikePanel({ subs }: { subs: Subscription[] }) {
  const hikes = hikeStories(subs);

  if (!hikes.length) {
    return <p className="text-sm text-muted">No price rises found. Unusual.</p>;
  }

  return (
    <ul className="space-y-4">
      {hikes.map((h) => (
        <li key={`${h.merchant}-${h.when}-${h.kind}`}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm text-ink">{h.merchant}</span>
            <span className="tnum text-xs text-muted">{pct(h.pct)}</span>
          </div>
          <div className="tnum mt-1 text-sm text-muted">
            {money(h.from)} <span className="text-faint">→</span>{" "}
            <span className="text-ink">{money(h.to)}</span>
          </div>
          <div className="mt-1 text-xs text-faint">
            {h.kind === "creep"
              ? `crept up ${h.steps} times, last on ${day(h.when)}`
              : `stepped up on ${day(h.when)}`}{" "}
            ·{" "}
            <span className="tnum text-downgrade">{money(h.annual)}/year</span>
          </div>
        </li>
      ))}
      <li className="border-t border-line pt-3 text-xs leading-relaxed text-faint">
        Nobody emailed you about these. We found them by comparing what you were
        charged, month by month.
      </li>
    </ul>
  );
}

export function ExcludedPanel({ groups }: { groups: ExcludedGroup[] }) {
  // Salary is money coming IN. Ranking it by amount alongside outgoings put
  // "₹95,000 a month" at the top of a panel about spending we ignored, which
  // reads as if we excluded ₹95,000 of charges. It goes last, labelled.
  const spending = groups.filter((g) => g.reason !== "salary");
  const income = groups.filter((g) => g.reason === "salary");

  return (
    <div>
      <ul className="space-y-3">
        {[...spending, ...income].map((g) => (
          <li
            key={g.reason}
            className="flex items-baseline justify-between gap-3 border-b border-line pb-3 last:border-b-0"
          >
            <div className="min-w-0">
              <div className="text-sm text-ink">{g.label}</div>
              <div className="truncate text-xs text-faint">
                {g.merchants.map((m) => m.canonical).join(" · ")}
              </div>
            </div>
            <div className="tnum shrink-0 text-right text-sm text-muted">
              {money(g.approx_monthly)}
              <div className="text-[11px] text-faint">
                {g.reason === "salary" ? "received" : "a month"}
              </div>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-xs leading-relaxed text-faint">
        These repeat every month like a subscription does. They are not leaks,
        so we left them out of the total — we are not going to tell you to
        cancel your rent.
      </p>
    </div>
  );
}
