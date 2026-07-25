"use client";

import { createContext, useContext, useMemo, useState } from "react";
import type { Analysis, UsageTap } from "./types";

/** In memory only — no localStorage, no sessionStorage, no cookie.
 *
 *  Refreshing /dashboard loses the analysis and bounces home. That is the
 *  point: §16 promises the data is "discarded when you close this tab", and
 *  here there is nothing on disk for anyone to inspect, including us. */

interface SessionValue {
  analysis: Analysis | null;
  setAnalysis: (a: Analysis | null) => void;
  taps: Record<string, UsageTap>;
  setTap: (merchant: string, tap: UsageTap | null) => void;
  reset: () => void;
}

const Ctx = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [taps, setTaps] = useState<Record<string, UsageTap>>({});

  const value = useMemo<SessionValue>(
    () => ({
      analysis,
      setAnalysis,
      taps,
      setTap: (merchant, tap) =>
        setTaps((prev) => {
          const next = { ...prev };
          if (tap === null) delete next[merchant];
          else next[merchant] = tap;
          return next;
        }),
      reset: () => {
        setAnalysis(null);
        setTaps({});
      },
    }),
    [analysis, taps],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
