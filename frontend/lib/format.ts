/** Indian grouping throughout: 1,85,000 — not 185,000.
 *  The backend shipped this bug once already (Phase 1); en-IN gets it right. */

const RUPEES = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const RUPEES_PRECISE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const PLAIN = new Intl.NumberFormat("en-IN");

export const money = (n: number) => RUPEES.format(Math.round(n));
export const moneyPrecise = (n: number) => RUPEES_PRECISE.format(n);
export const count = (n: number) => PLAIN.format(n);

export function day(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

// Both en-IN and en-GB abbreviate September as "Sept", which leaves the scan
// column ragged next to "20 Jan". A fixed table is the only way to guarantee
// three characters.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Fixed-width "20 Jan" for the scan list. */
export function scanDay(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return `${String(d.getDate()).padStart(2, "0")} ${MONTHS[d.getMonth()]}`;
}

export function shortDay(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

export const PERIOD_LABEL: Record<string, string> = {
  weekly: "weekly",
  monthly: "monthly",
  quarterly: "quarterly",
  annual: "yearly",
};

export const pct = (n: number) => `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
