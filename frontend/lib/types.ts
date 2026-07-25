/** Mirrors backend/main.py:analyze() exactly. If the backend contract moves,
 *  this file is the one place the frontend has to follow it. */

export type Band = "keep" | "review" | "downgrade" | "cancel";
export type ActionKind = "cancel" | "downgrade" | "renegotiate" | "keep";
export type UsageTap = "yes" | "no" | "unsure";
export type Period = "weekly" | "monthly" | "quarterly" | "annual";

export interface Action {
  kind: ActionKind;
  label: string;
  url: string | null;
  menu_path: string | null;
  est_annual_saving: number;
}

export interface PriceChange {
  from_amount: number;
  to_amount: number;
  changed_on: string;
  pct: number;
  annual_impact: number;
  kind: "step" | "creep";
}

export interface Subscription {
  canonical: string;
  category: string;
  period: Period;
  period_days: number;
  confidence: number;
  current_amount: number;
  annual_cost: number;
  next_charge_date: string | null;
  occurrences: number;
  leak_score: number;
  band: Band;
  /** Weighted contributions in POINTS — these sum to leak_score. */
  score_breakdown: Record<string, number>;
  why_this_score: string[];
  dormancy_signals: string[];
  redundant_with: string[];
  cheaper_tier: { name: string; price: number } | null;
  raw_variants: string[];
  price_changes: PriceChange[];
  price_history: { date: string; amount: number }[];
  action: Action;
}

export interface ExcludedGroup {
  reason: "rent" | "salary" | "emi" | "sip" | "cc_bill" | "utility";
  label: string;
  occurrences: number;
  approx_monthly: number;
  merchants: {
    canonical: string;
    detail: string;
    occurrences: number;
    raw_variants: string[];
  }[];
}

export interface Portfolio {
  monthly_leak: number;
  annual_leak: number;
  annual_savings_if_actioned: number;
  portfolio_leak_score: number;
  subscription_count: number;
  excluded_count: number;
  excluded_transactions: number;
  transactions_analyzed: number;
}

export interface ScanReceipt {
  source: string;
  scanned: number;
  matched: number;
  ignored: number;
  unparsed: number;
  llm_recovered: number;
  attachments_opened: number;
  bytes_stored: number;
  notes: string[];
  summary: string;
}

/** A real sample of the transactions read, for the scan screen. Not
 *  reconstructed — these are the actual records, evenly sampled across the
 *  window, with the merchant they were matched to. */
export interface StreamedTransaction {
  date: string;
  merchant_raw: string;
  amount: number;
  source: string;
  matched: string | null;
}

export interface Analysis {
  profile?: string;
  receipt?: ScanReceipt;
  stream?: StreamedTransaction[];
  subscriptions: Subscription[];
  excluded: ExcludedGroup[];
  portfolio: Portfolio;
}

export const BAND_LABEL: Record<Band, string> = {
  keep: "Keep",
  review: "Review",
  downgrade: "Downgrade",
  cancel: "Cancel",
};

/** Reserved status ramp. Always rendered alongside the band's text label — a
 *  colour never carries the meaning on its own. */
export const BAND_COLOR: Record<Band, string> = {
  keep: "var(--color-keep)",
  review: "var(--color-review)",
  downgrade: "var(--color-downgrade)",
  cancel: "var(--color-cancel)",
};

/** Fixed categorical order, never cycled. Validated as a set against the dark
 *  surface: worst adjacent CVD ΔE 8.4, worst normal-vision ΔE 19.3. */
export const SERIES = [
  "var(--color-s1)",
  "var(--color-s2)",
  "var(--color-s3)",
  "var(--color-s4)",
  "var(--color-s5)",
  "var(--color-s6)",
] as const;

export const SCORE_TERM_LABEL: Record<string, string> = {
  cost: "Cost",
  dormancy: "Not using it",
  redundancy: "Duplicate service",
  unnoticed_hike: "Price rose",
  cheaper_tier: "Cheaper tier exists",
};
