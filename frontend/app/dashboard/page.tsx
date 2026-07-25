"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import { CategorySpend } from "@/components/CategorySpend";
import { ExcludedPanel, HikePanel } from "@/components/Panels";
import { SubscriptionRow } from "@/components/SubscriptionRow";
import { applyTap } from "@/lib/demo";
import { count, money } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function Dashboard() {
  const router = useRouter();
  const { analysis, taps, setTap, reset } = useSession();

  useEffect(() => {
    if (!analysis) router.replace("/");
  }, [analysis, router]);

  // Taps re-score live, so the totals below must be derived, never cached.
  const subs = useMemo(
    () =>
      (analysis?.subscriptions ?? [])
        .map((s) => applyTap(s, taps[s.canonical]))
        .sort((a, b) => b.leak_score - a.leak_score),
    [analysis, taps],
  );

  if (!analysis) return null;

  const p = analysis.portfolio;
  const savings = subs.reduce((sum, s) => sum + s.action.est_annual_saving, 0);
  const weighted = subs.reduce((sum, s) => sum + s.leak_score * s.annual_cost, 0);
  const totalCost = subs.reduce((sum, s) => sum + s.annual_cost, 0);
  const portfolioScore = totalCost ? Math.round((weighted / totalCost) * 10) / 10 : 0;

  return (
    <main className="mx-auto max-w-6xl px-6 pb-24 pt-10 sm:px-8">
      <header className="flex items-baseline justify-between">
        <Link href="/" className="font-mono text-sm text-ink hover:text-brass">
          sieve
        </Link>
        <button
          type="button"
          onClick={() => {
            reset();
            router.push("/");
          }}
          className="text-xs text-muted underline underline-offset-4 hover:text-ink"
        >
          Delete everything
        </button>
      </header>

      {/* The hero is one number. Everything else on the page is smaller. */}
      <section className="pt-16 sm:pt-20">
        <p className="text-sm text-muted">You are leaking</p>
        <div className="tnum mt-2 text-6xl leading-none text-ink sm:text-8xl">
          {money(p.monthly_leak)}
        </div>
        <p className="mt-3 text-sm text-muted">
          every month · {money(p.annual_leak)} a year
        </p>

        <div className="mt-10 border-t border-brassdim pt-6">
          <p className="text-lg text-ink sm:text-2xl">
            Act on all {subs.length} recommendations and save{" "}
            <span className="tnum text-brass">{money(savings)}</span> a year.
          </p>
        </div>

        <dl className="mt-8 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          {[
            ["Portfolio leak score", `${portfolioScore}`],
            ["Subscriptions", count(subs.length)],
            ["Correctly excluded", count(p.excluded_count)],
            ["Transactions read", count(p.transactions_analyzed)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-[11px] text-faint">{label}</dt>
              <dd className="tnum mt-0.5 text-xl text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="mt-16">
        <div className="flex items-baseline justify-between">
          <h2 className="text-xs uppercase tracking-wider text-faint">
            Subscriptions
          </h2>
          <p className="text-[11px] text-faint">
            Open a row to see how its score was calculated
          </p>
        </div>

        <div className="mt-4 overflow-hidden rounded-sm border border-line bg-surface">
          <ul>
            {subs.map((s) => (
              <SubscriptionRow
                key={s.canonical}
                sub={s}
                tap={taps[s.canonical]}
                onTap={(t) => setTap(s.canonical, t)}
              />
            ))}
          </ul>
        </div>
      </section>

      <div className="mt-12 grid gap-6 lg:grid-cols-3">
        <section className="rounded-sm border border-line bg-surface p-6">
          <h2 className="mb-5 text-xs uppercase tracking-wider text-faint">
            Prices that rose
          </h2>
          <HikePanel subs={subs} />
        </section>

        <section className="rounded-sm border border-line bg-surface p-6">
          <h2 className="mb-5 text-xs uppercase tracking-wider text-faint">
            Where the money goes
          </h2>
          <CategorySpend subs={subs} />
        </section>

        <section className="rounded-sm border border-line bg-surface p-6">
          <h2 className="mb-5 text-xs uppercase tracking-wider text-faint">
            Correctly excluded
          </h2>
          <ExcludedPanel groups={analysis.excluded} />
        </section>
      </div>

      <p className="mt-14 max-w-2xl text-xs leading-relaxed text-faint">
        Nothing on this page was written to a database, because there isn&rsquo;t
        one. Close the tab and it is gone.
      </p>
    </main>
  );
}
