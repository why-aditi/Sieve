"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Collapse } from "@/components/Collapse";
import { DEFAULT_PROFILE, PROFILES } from "@/lib/demo";
import { money } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function Landing() {
  const router = useRouter();
  const { setAnalysis, reset } = useSession();

  // Zero network. The analysis is already in the bundle, so this cannot fail,
  // cannot cold-start, and cannot be slow — the judge's path (§6.2).
  function seeSampleData() {
    reset();
    setAnalysis(PROFILES[DEFAULT_PROFILE].data);
    router.push("/scanning");
  }

  const headline = PROFILES[DEFAULT_PROFILE].data.portfolio.monthly_leak;

  return (
    <main className="mx-auto max-w-5xl px-6 pb-24 pt-10 sm:px-8">
      <header className="flex items-baseline justify-between">
        <span className="font-mono text-sm tracking-tight text-ink">sieve</span>
        <span className="text-xs text-faint">No account. No database.</span>
      </header>

      <section className="pt-20 sm:pt-28">
        <h1 className="font-display text-[2.75rem] leading-[1.05] tracking-tight text-ink sm:text-6xl md:text-7xl">
          You&rsquo;re leaking
          <br />
          <span className="tnum text-brass">{money(headline)}</span> a month.
        </h1>
        <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted">
          Find out in 30 seconds. Point Sieve at a bank statement and it finds
          the subscriptions you forgot, the prices that rose without telling
          you, and what to do about each one.
        </p>

        <div className="mt-10 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
          <button
            type="button"
            onClick={seeSampleData}
            className="rounded-sm bg-brass px-6 py-3.5 text-sm font-medium text-ground transition-colors hover:bg-ink"
          >
            See it with sample data
          </button>
          <Link
            href="/connect"
            className="text-sm text-muted underline underline-offset-4 transition-colors hover:text-ink"
          >
            Upload your own statement →
          </Link>
        </div>
        <p className="mt-4 text-xs text-faint">
          Sample data opens instantly. Nothing to sign up for.
        </p>
      </section>

      <section className="mt-28 border-t border-line pt-12 sm:mt-36">
        <h2 className="text-xs uppercase tracking-wider text-faint">
          Why this is hard
        </h2>
        <p className="mt-4 max-w-2xl text-lg leading-relaxed text-ink">
          Your statement writes the same subscription four different ways.
        </p>

        <div className="mt-10">
          <Collapse />
        </div>

        <p className="mt-10 max-w-2xl text-sm leading-relaxed text-muted">
          Group these naively and you get four subscriptions of one charge each,
          which means you detect nothing. Sieve collapses them into one merchant
          before it looks for a pattern. That step is most of the work.
        </p>
      </section>

      <section className="mt-24 border-t border-line pt-12">
        <div className="grid gap-10 sm:grid-cols-3">
          <div>
            <h3 className="text-sm text-ink">Every number is arithmetic</h3>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              Leak scores are a visible weighted formula. Open any row and you
              can see each term&rsquo;s contribution add up to the score.
            </p>
          </div>
          <div>
            <h3 className="text-sm text-ink">It says no</h3>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              Rent, EMIs, SIPs and salary repeat monthly too. Sieve keeps them
              out and shows you what it excluded, and why.
            </p>
          </div>
          <div>
            <h3 className="text-sm text-ink">Nothing is stored</h3>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              Your data is parsed in memory and discarded when you close this
              tab. There is no database — refresh the page and it is gone.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
