"use client";

/** The signature element: four raw bank strings resolving into one
 *  subscription. This is §7's thesis made visible — naive grouping finds four
 *  subscriptions of one charge each and detects nothing. It is the one place
 *  in the design where boldness is spent. */

const STRINGS = [
  "UPI/NETFLIX BILLDESK/928471/PAYMENT",
  "ACH-D- NETFLIX ENTERTAINMENT SERVICES",
  "NEFT-NETFLIXENT-8821-RTGS",
  "POS 4471XXXX2210 NETFLIX.COM MUMBAI",
];

export function Collapse() {
  return (
    <div className="grid gap-8 md:grid-cols-[minmax(0,30rem)_auto_auto] md:items-center md:gap-6">
      <ul className="space-y-2 min-w-0">
        {STRINGS.map((s, i) => (
          <li
            key={s}
            className="anim-in truncate rounded-sm border border-line bg-surface px-3 py-2 font-mono text-[11px] leading-relaxed text-muted sm:text-xs"
            style={{ animationDelay: `${i * 90}ms` }}
          >
            {s}
          </li>
        ))}
      </ul>

      {/* Brace + arrow. Decorative, so hidden from assistive tech — the
          sentence below states the same relationship in words. */}
      <div
        aria-hidden
        className="anim-in hidden md:flex md:items-center md:gap-3"
        style={{ animationDelay: "400ms" }}
      >
        <svg width="30" height="150" viewBox="0 0 30 150" fill="none">
          <path
            d="M1 1c0 34 27 23 27 74s-27 41-27 74"
            stroke="var(--color-brass)"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
        <span className="text-xl text-brass">→</span>
      </div>

      <div
        className="anim-settle rounded-sm border border-brassdim bg-raised px-5 py-4"
        style={{ animationDelay: "560ms" }}
      >
        <div className="text-sm font-medium text-ink">Netflix</div>
        <div className="tnum mt-1 text-2xl text-brass">₹649</div>
        <div className="mt-1 text-xs text-faint">monthly · 18 charges</div>
      </div>
    </div>
  );
}
