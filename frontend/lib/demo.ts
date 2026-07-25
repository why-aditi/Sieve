import family from "./data/family.json";
import familyCombined from "./data/family_combined.json";
import student from "./data/student.json";
import studentCombined from "./data/student_combined.json";
import youngProfessional from "./data/young_professional.json";
import youngProfessionalCombined from "./data/young_professional_combined.json";
import type { Analysis, Subscription, UsageTap } from "./types";

/** Bundled, not fetched.
 *
 *  Non-negotiable #3: the demo path makes zero network calls. Render's free
 *  tier cold-starts at ~50s, so a judge's first click would otherwise hang on
 *  a spinner. All three profiles are ~21KB each — cheap enough to ship in the
 *  bundle and be immune to the backend being asleep, rate-limited, or gone. */

export const PROFILES = {
  student: {
    label: "Student",
    blurb: "Eight subscriptions, a ₹0 trial that converted, two music apps",
    data: student as unknown as Analysis,
  },
  young_professional: {
    label: "Young professional",
    blurb: "Nine subscriptions, a silent price rise, rent and two EMIs excluded",
    data: youngProfessional as unknown as Analysis,
  },
  family: {
    label: "Family",
    blurb: "Four streaming services, broadband creeping up 8% a year",
    data: family as unknown as Analysis,
  },
} as const;

export type ProfileKey = keyof typeof PROFILES;
export const DEFAULT_PROFILE: ProfileKey = "young_professional";

/** SMS + email receipts for the same account, deduped (§6.7).
 *
 *  This is what the Email card's "Try with demo account" loads. It is the only
 *  place multi-source ingestion is visible: 2,918 messages in, 800 charges out,
 *  118 of them seen twice and merged into one. Same corpus, both renderings,
 *  real adapter output — the merge count is measured, not written. */
export const COMBINED: Record<ProfileKey, Analysis> = {
  student: studentCombined as unknown as Analysis,
  young_professional: youngProfessionalCombined as unknown as Analysis,
  family: familyCombined as unknown as Analysis,
};

/** Re-score one subscription for a usage tap, client-side.
 *
 *  The backend owns scoring; this mirrors the two rules the tap touches so the
 *  judge sees the score move the instant they answer, with no round trip. The
 *  weights come from §11 and the arithmetic is the same — dormancy is the
 *  0.25 term, and "yes" overrides every proxy to zero.
 *
 *  ponytail: duplicated rule, deliberately. Wire it to POST /analyze if the
 *  tap ever needs to affect anything beyond this one term. */
const DORMANCY_WEIGHT = 25;
const TAP_DORMANCY: Record<UsageTap, number> = { yes: 0, unsure: 0.6, no: 1 };

export function applyTap(sub: Subscription, tap: UsageTap | undefined): Subscription {
  if (!tap) return sub;

  const breakdown = { ...sub.score_breakdown };
  breakdown.dormancy = Math.round(DORMANCY_WEIGHT * TAP_DORMANCY[tap] * 100) / 100;

  const leak_score =
    Math.round(Object.values(breakdown).reduce((a, b) => a + b, 0) * 100) / 100;

  const band =
    leak_score <= 30 ? "keep"
    : leak_score <= 60 ? "review"
    : leak_score <= 80 ? "downgrade"
    : "cancel";

  return { ...sub, score_breakdown: breakdown, leak_score, band };
}

export function bandOf(score: number) {
  return score <= 30 ? "keep" : score <= 60 ? "review" : score <= 80 ? "downgrade" : "cancel";
}
