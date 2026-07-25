"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DEFAULT_PROFILE, PROFILES } from "@/lib/demo";
import { useSession } from "@/lib/session";

const API = process.env.NEXT_PUBLIC_API_URL;

/** §16: consent copy is shown BEFORE any grant, on each card, in the words of
 *  the thing being granted — not buried in a policy nobody opens. */
const CARDS = [
  {
    id: "email",
    title: "Email",
    what: "Payment receipts from banks and merchants",
    consent: [
      "We read messages from 40 known bank and payment senders only.",
      "We never open attachments.",
      "Your access token is held in memory for this tab and never written down.",
    ],
    gated: true,
  },
  {
    id: "sms",
    title: "SMS",
    what: "The bank alerts already on your phone",
    consent: [
      "A web page cannot read your SMS — no browser API exists for it.",
      "So you paste them, or upload an SMS Backup & Restore export.",
      "Nothing is uploaded to a server you don't control.",
    ],
    gated: false,
  },
  {
    id: "statement",
    title: "Statement",
    what: "A CSV exported from net banking",
    consent: [
      "Columns are matched loosely, so slight header differences still work.",
      "The file is parsed in your session and discarded.",
    ],
    gated: false,
  },
] as const;

export default function Connect() {
  const router = useRouter();
  const { setAnalysis, reset } = useSession();
  const [api, setApi] = useState<"checking" | "up" | "down">("checking");

  // The API only matters on this screen. The demo path never touches it.
  useEffect(() => {
    if (!API) return setApi("down");
    fetch(`${API}/health`)
      .then((r) => setApi(r.ok ? "up" : "down"))
      .catch(() => setApi("down"));
  }, []);

  function tryDemoAccount() {
    reset();
    setAnalysis(PROFILES[DEFAULT_PROFILE].data);
    router.push("/scanning");
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
                api === "up" ? "var(--color-keep)" : "var(--color-faint)",
            }}
          />
          {api === "up" ? "Service online" : "Service unavailable"}
        </span>
      </header>

      <h1 className="mt-16 text-3xl tracking-tight text-ink sm:text-4xl">
        Choose what Sieve can see.
      </h1>
      <p className="mt-4 max-w-2xl leading-relaxed text-muted">
        Each of these works on its own. Grant one, grant all three, or grant
        none and look at the sample data instead.
      </p>

      <div className="mt-12 grid gap-5 md:grid-cols-3">
        {CARDS.map((card) => (
          <section
            key={card.id}
            className="flex flex-col rounded-sm border border-line bg-surface p-5"
          >
            <h2 className="text-sm font-medium text-ink">{card.title}</h2>
            <p className="mt-1 text-xs text-muted">{card.what}</p>

            <ul className="mt-5 space-y-2 border-t border-line pt-4">
              {card.consent.map((line) => (
                <li key={line} className="text-[11px] leading-relaxed text-faint">
                  {line}
                </li>
              ))}
            </ul>

            <div className="mt-auto flex flex-col gap-2 pt-6">
              <button
                type="button"
                disabled
                title="Available after Google verification — use the demo account"
                className="cursor-not-allowed rounded-sm border border-line px-3 py-2 text-xs text-faint"
              >
                {card.id === "email"
                  ? "Connect Google"
                  : card.id === "sms"
                    ? "Paste or upload"
                    : "Upload CSV"}
              </button>

              {card.gated && (
                <button
                  type="button"
                  onClick={tryDemoAccount}
                  className="rounded-sm bg-brass px-3 py-2 text-xs font-medium text-ground transition-colors hover:bg-ink"
                >
                  Try with demo account
                </button>
              )}
            </div>
          </section>
        ))}
      </div>

      <p className="mt-8 max-w-2xl text-xs leading-relaxed text-faint">
        Gmail&rsquo;s read scope needs Google verification before strangers can
        use it, so the Connect buttons are switched off here rather than
        pretending to work. Everything the finished flow produces is in the demo
        account, on real parsing, with nothing faked downstream.
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
