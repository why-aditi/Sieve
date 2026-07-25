"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL;

// ponytail: client-side fetch on purpose. Render's free tier sleeps, and a cold
// backend should degrade to a grey dot, not a 500 on the landing page.
function useHealth() {
  const [state, setState] = useState<"checking" | "ok" | "down">("checking");
  useEffect(() => {
    if (!API) {
      setState("down");
      return;
    }
    fetch(`${API}/health`)
      .then((r) => setState(r.ok ? "ok" : "down"))
      .catch(() => setState("down"));
  }, []);
  return state;
}

const DOT = {
  checking: ["bg-neutral-500", "checking API…"],
  ok: ["bg-emerald-500", "API live"],
  down: ["bg-neutral-600", "API unreachable"],
} as const;

export default function Home() {
  const health = useHealth();
  const [color, label] = DOT[health];

  return (
    <main className="min-h-dvh bg-neutral-950 text-neutral-100 flex items-center justify-center px-6">
      <div className="max-w-2xl w-full">
        <h1 className="text-5xl font-semibold tracking-tight">Sieve</h1>
        <p className="mt-6 text-2xl leading-snug text-neutral-300">
          You&rsquo;re probably leaking ₹4,000 a month.
          <br />
          Find out in 30 seconds.
        </p>
        <p className="mt-6 text-sm text-neutral-500">
          Hidden subscription &amp; recurring-payment leak detector. Nothing is
          stored — your data is parsed in memory and discarded when you close
          this tab.
        </p>
        <div className="mt-12 flex items-center gap-2 text-sm text-neutral-500">
          <span className={`h-2 w-2 rounded-full ${color}`} />
          {label}
        </div>
      </div>
    </main>
  );
}
