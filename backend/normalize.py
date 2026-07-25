"""Merchant normalization cascade — spec §7.

Four steps, cheapest first:
  1. regex cleanup (NOISE patterns, §7 verbatim)
  2. alias dictionary (~60 Indian services), longest key first
  3. rapidfuzz token_set_ratio > 85 against alias keys
  4. one batched Groq call for whatever is still unmatched

Every step is pure except step 4, which is wrapped so any failure — no API key,
no network, bad JSON, rate limit — falls back to the cleaned string with
category "other". The pipeline never blocks on the LLM.

Set GROQ_API_KEY to enable step 4; GROQ_MODEL overrides the model.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from rapidfuzz import fuzz

from config import GROQ_MODEL, groq_key  # noqa: F401  (imported for .env load)
from models import MerchantCluster, Transaction

# ---------------------------------------------------------------- step 1: clean

# §7 verbatim. Order matters: the dot survives until pattern 4 consumes ".COM".
NOISE = [
    r"^(UPI|ACH[-\s]?D?|NEFT|IMPS|RTGS|POS|ATM|MANDATE|ECS|NACH)[-/\s]*",
    r"\b\d{4,}\b",                      # reference / card digit runs
    r"\b(PVT|PRIVATE|LTD|LIMITED|INDIA|IN|SERVICES|ENTERTAINMENT|TECHNOLOGIES)\b",
    r"\.(COM|IN|CO|NET)\b",
    r"\b(MUMBAI|DELHI|BANGALORE|BENGALURU|PUNE|HYDERABAD|CHENNAI|KOLKATA|GURGAON|NOIDA)\b",
    r"[^A-Z0-9\s]",
]


def clean(s: str) -> str:
    s = s.upper()
    for p in NOISE:
        s = re.sub(p, " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------- step 2: aliases

# ponytail: substring lookup, longest key first — not exact equality. Real bank
# strings glue the brand to other tokens ("NETFLIXENT", "SPOTIFYINDIA"), so
# containment is what actually matches. Longest-first stops "JIO" from
# swallowing "JIOSAAVN".
ALIASES: dict[str, tuple[str, str]] = {
    # streaming
    "NETFLIX": ("Netflix", "streaming"),
    "HOTSTAR": ("JioHotstar", "streaming"),
    "JIOHOTSTAR": ("JioHotstar", "streaming"),
    "DISNEY": ("JioHotstar", "streaming"),
    "PRIMEVIDEO": ("Amazon Prime", "streaming"),
    "AMAZONPRIME": ("Amazon Prime", "streaming"),
    "AMAZON PRIME": ("Amazon Prime", "streaming"),
    "ZEE5": ("Zee5", "streaming"),
    "ZEE": ("Zee5", "streaming"),
    "SONYLIV": ("SonyLIV", "streaming"),
    "SONY PICTURES": ("SonyLIV", "streaming"),
    "YOUTUBEPREMIUM": ("YouTube Premium", "streaming"),
    "GOOGLEYOUTUBE": ("YouTube Premium", "streaming"),
    "GOOGLE YT": ("YouTube Premium", "streaming"),
    "VOOT": ("Voot", "streaming"),
    "AHA": ("Aha", "streaming"),
    "APPLETV": ("Apple TV+", "streaming"),
    # music
    "SPOTIFY": ("Spotify", "music"),
    "JIOSAAVN": ("JioSaavn", "music"),
    "SAAVN": ("JioSaavn", "music"),
    "GAANA": ("Gaana", "music"),
    "WYNK": ("Wynk Music", "music"),
    "APPLEMUSIC": ("Apple Music", "music"),
    # saas
    "ADOBE": ("Adobe CC", "saas"),
    "CANVA": ("Canva", "saas"),
    "NOTION": ("Notion", "saas"),
    "FIGMA": ("Figma", "saas"),
    "OPENAI": ("ChatGPT Plus", "saas"),
    "CHATGPT": ("ChatGPT Plus", "saas"),
    "GITHUB": ("GitHub", "saas"),
    "SLACK": ("Slack", "saas"),
    "ZOOM": ("Zoom", "saas"),
    "GRAMMARLY": ("Grammarly", "saas"),
    "LINKEDIN": ("LinkedIn Premium", "saas"),
    "COURSERA": ("Coursera", "saas"),
    "UDEMY": ("Udemy", "saas"),
    # cloud
    "GOOGLEONE": ("Google One", "cloud"),
    "GOOGLE ONE": ("Google One", "cloud"),
    "GOOGLE": ("Google One", "cloud"),
    "ICLOUD": ("iCloud", "cloud"),
    "DROPBOX": ("Dropbox", "cloud"),
    "ONEDRIVE": ("OneDrive", "cloud"),
    # fitness
    "CULTFIT": ("Cult.fit", "fitness"),
    "CULT FIT": ("Cult.fit", "fitness"),
    "CUREFIT": ("Cult.fit", "fitness"),
    "HEALTHIFYME": ("HealthifyMe", "fitness"),
    "GOLDSGYM": ("Gold's Gym", "fitness"),
    # telecom
    "AIRTEL": ("Airtel", "telecom"),
    "JIO": ("Jio", "telecom"),
    "VODAFONE": ("Vi", "telecom"),
    "ACTFIBERNET": ("ACT Fibernet", "telecom"),
    "ACTFIBER": ("ACT Fibernet", "telecom"),
    "ATRIA": ("ACT Fibernet", "telecom"),
    "HATHWAY": ("Hathway", "telecom"),
    "TATASKY": ("Tata Play", "telecom"),
    "TATA PLAY": ("Tata Play", "telecom"),
    # food
    "SWIGGYONE": ("Swiggy One", "food"),
    "SWIGGY ONE": ("Swiggy One", "food"),
    "BUNDL": ("Swiggy One", "food"),
    "SWIGGY": ("Swiggy", "food"),
    "ZOMATOGOLD": ("Zomato Gold", "food"),
    "ZOMATO": ("Zomato", "food"),
    "BIGBASKET": ("BigBasket", "food"),
    "BLINKIT": ("Blinkit", "food"),
    # other recurring-adjacent brands that show up as noise
    "AMAZON": ("Amazon", "retail"),
    "FLIPKART": ("Flipkart", "retail"),
    "MYNTRA": ("Myntra", "retail"),
    "UBER": ("Uber", "transport"),
    "OLACABS": ("Ola", "transport"),
    "IRCTC": ("IRCTC", "transport"),
    "BHARATPETRO": ("Bharat Petroleum", "fuel"),
    "INDIAN OIL": ("Indian Oil", "fuel"),
    "HP PETRO": ("HP Petrol", "fuel"),
}

# Longest first so "JIOSAAVN" wins over "JIO" and "SWIGGYONE" over "SWIGGY".
_ALIAS_KEYS = sorted(ALIASES, key=len, reverse=True)

# The key must start at a word boundary. Bare substring matching resolves
# M-AHA-DISCOM (the Maharashtra electricity board) to the streaming service
# "Aha" — the same failure mode as YOUTUBE-PR-EMI-UM in exclusions.py. A
# TRAILING boundary is deliberately not required: bank strings glue suffixes on
# ("NETFLIXENT", "SPOTIFYINDIA", "CULTFITIND") and those must still match.
_ALIAS_PATTERNS = [(re.compile(r"\b" + re.escape(k)), k) for k in _ALIAS_KEYS]

FUZZY_THRESHOLD = 85


def resolve(raw: str) -> tuple[str, str, str]:
    """(canonical, category, method). Steps 1-3 only — never calls the LLM."""
    cleaned = clean(raw)
    if not cleaned:
        return raw.strip() or "Unknown", "other", "empty"

    for pattern, key in _ALIAS_PATTERNS:
        if pattern.search(cleaned):
            canonical, category = ALIASES[key]
            return canonical, category, "alias"

    best_key, best_score = None, 0.0
    for key in _ALIAS_KEYS:
        score = fuzz.token_set_ratio(cleaned, key)
        if score > best_score:
            best_key, best_score = key, score
    if best_key and best_score > FUZZY_THRESHOLD:
        canonical, category = ALIASES[best_key]
        return canonical, category, "fuzzy"

    return cleaned, "other", "unmatched"


# ---------------------------------------------------------- step 4: LLM fallback

CATEGORIES = [
    "streaming", "music", "saas", "cloud", "fitness",
    "telecom", "food", "insurance", "utility", "other",
]

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "merchants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "canonical": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                },
                "required": ["raw", "canonical", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["merchants"],
    "additionalProperties": False,
}

_LLM_CACHE: dict[str, tuple[str, str]] = {}
MAX_LLM_BATCH = 60

def llm_resolve(cleaned: list[str]) -> dict[str, tuple[str, str]]:
    """One batched Groq call. Returns {} on ANY failure — the caller keeps going.

    Cached by cleaned string, so a repeat scan in the same process is free.
    """
    todo = [c for c in dict.fromkeys(cleaned) if c not in _LLM_CACHE][:MAX_LLM_BATCH]
    if not todo or not groq_key():
        return {c: _LLM_CACHE[c] for c in cleaned if c in _LLM_CACHE}

    try:
        from groq import Groq

        response = Groq().chat.completions.create(
            model=GROQ_MODEL,
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "merchant_normalization",
                    "strict": True,
                    "schema": _LLM_SCHEMA,
                },
            },
            messages=[
                {"role": "system", "content": (
                    "You normalize Indian bank-statement merchant strings. For each "
                    "input line return the canonical consumer brand name and one "
                    f"category from {CATEGORIES}. Echo `raw` back exactly as given. "
                    "If you do not recognise a string, repeat it as the canonical "
                    "name and use category 'other'. JSON only."
                )},
                {"role": "user", "content": "\n".join(todo)},
            ],
        )
        payload = json.loads(response.choices[0].message.content)
        for item in payload["merchants"]:
            if item["raw"] in todo and item["category"] in CATEGORIES:
                _LLM_CACHE[item["raw"]] = (item["canonical"], item["category"])
    except Exception:
        # ponytail: bare except on purpose. Detection must not care *why* the
        # LLM failed — no key, no network, rate limit, a deprecated model ID, a
        # truncated response — all of them mean "use the cleaned string".
        # §2: never block the pipeline on the LLM.
        pass

    return {c: _LLM_CACHE[c] for c in cleaned if c in _LLM_CACHE}


# ------------------------------------------------------------------ clustering


def cluster(txns: list[Transaction], use_llm: bool = False) -> list[MerchantCluster]:
    """Normalize then group by canonical merchant (§4's CLUSTER box).

    Unrecognised merchants keep their cleaned string as the canonical name, then
    get fuzzy-merged against each other — otherwise a decoy whose two templates
    clean to different strings splits into two half-frequency clusters and
    silently disappears from both recurrence detection and the excluded panel.
    """
    resolved: dict[str, tuple[str, str]] = {}
    unmatched: list[str] = []
    for t in txns:
        if t.merchant_raw in resolved:
            continue
        canonical, category, method = resolve(t.merchant_raw)
        resolved[t.merchant_raw] = (canonical, category)
        if method == "unmatched":
            unmatched.append(canonical)

    if use_llm and unmatched:
        for raw, (canonical, category) in list(resolved.items()):
            hit = llm_resolve(unmatched).get(canonical)
            if hit:
                resolved[raw] = hit

    groups: dict[str, list[Transaction]] = {}
    meta: dict[str, str] = {}
    for t in txns:
        canonical, category = resolved[t.merchant_raw]
        groups.setdefault(canonical, []).append(t)
        meta[canonical] = category

    merged = _merge_similar([
        MerchantCluster(
            canonical=canonical,
            category=meta[canonical],
            raw_variants=sorted({t.merchant_raw for t in group}),
            transactions=sorted(group, key=lambda t: t.date),
        )
        for canonical, group in groups.items()
    ])
    return merged


def _merge_similar(clusters: list[MerchantCluster]) -> list[MerchantCluster]:
    """Fuzzy-merge leftover `other` clusters against each other."""
    known = [c for c in clusters if c.category != "other"]
    others = sorted((c for c in clusters if c.category == "other"),
                    key=lambda c: len(c.transactions), reverse=True)

    out: list[MerchantCluster] = []
    for c in others:
        for target in out:
            if fuzz.token_set_ratio(c.canonical, target.canonical) > FUZZY_THRESHOLD:
                target.raw_variants = sorted(set(target.raw_variants) | set(c.raw_variants))
                target.transactions = sorted(
                    target.transactions + c.transactions, key=lambda t: t.date)
                break
        else:
            out.append(c)
    return known + out


@lru_cache(maxsize=4096)
def clean_cached(s: str) -> str:
    return clean(s)


if __name__ == "__main__":
    # Self-check: `python normalize.py` tells you whether the Groq key works,
    # without needing the rest of the pipeline.
    probes = ["ACH-D- WHITEHAT JR EDUCATION", "UPI/RAPIDOBIKE/443112/PAYMENT"]
    print(f"model: {GROQ_MODEL}")
    print(f"GROQ_API_KEY: {'set' if os.getenv('GROQ_API_KEY') else 'NOT SET'}")
    for raw in probes:
        print(f"  cascade  {raw!r} -> {resolve(raw)}")
    got = llm_resolve([clean(p) for p in probes])
    if got:
        for cleaned, (canonical, category) in got.items():
            print(f"  groq     {cleaned!r} -> {canonical} / {category}")
        print("\nLLM step 4 is live.")
    else:
        print("\nLLM step 4 inactive — falling back to cleaned strings. "
              "Detection is unaffected.")
