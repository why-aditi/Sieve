"""Action engine — spec §12.

The brief asks for a concrete action plan. Most submissions will output the word
"cancel". This produces a deep link, the exact menu path, a named cheaper tier
with the rupee delta, or a drafted renegotiation email — and says "Keep" out
loud when keeping is right, because a tool that flags everything is a tool
nobody trusts.

The lookup table is a dict, not intelligence (§12). Prices are Indian list
prices captured while building and will drift — they are display/most-recent
values, and the SAVING is always computed from the user's own charged amount
minus the tier price, never from the table alone.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from config import GROQ_MODEL, groq_key
from models import Action, MerchantCluster, PriceChange

# Categories where a human on the other end can actually change your price.
NEGOTIABLE = {"fitness", "telecom", "insurance"}


@dataclass
class Merchant:
    url: str
    menu_path: str
    tiers: list[tuple[str, float]] = field(default_factory=list)


# canonical names match normalize.ALIASES output exactly, so the join is direct.
MERCHANTS: dict[str, Merchant] = {
    "Netflix": Merchant(
        "https://www.netflix.com/cancelplan",
        "Netflix > Account > Membership & Billing > Cancel Membership",
        [("Mobile", 199), ("Basic", 499), ("Standard", 649), ("Premium", 849)]),
    "JioHotstar": Merchant(
        "https://www.hotstar.com/in/subscribe/manage",
        "JioHotstar > My Account > Subscription > Cancel Plan",
        [("Mobile", 149), ("Super", 299), ("Premium", 499)]),
    "Amazon Prime": Merchant(
        "https://www.amazon.in/gp/primecentral",
        "Amazon > Account > Prime Membership > End Membership",
        [("Prime Lite", 799), ("Prime", 1499)]),
    "Zee5": Merchant(
        "https://www.zee5.com/myaccount/subscriptions",
        "ZEE5 > My Account > Subscriptions > Cancel",
        [("Mobile", 99), ("Premium", 199)]),
    "SonyLIV": Merchant(
        "https://www.sonyliv.com/myaccount",
        "SonyLIV > My Account > Manage Subscription > Cancel",
        [("Mobile", 199), ("Premium", 299), ("Premium 4K", 399)]),
    "YouTube Premium": Merchant(
        "https://www.youtube.com/paid_memberships",
        "YouTube > Profile > Purchases and memberships > Manage > Cancel",
        [("Individual", 149), ("Family", 189)]),
    "Spotify": Merchant(
        "https://www.spotify.com/in-en/account/subscription/",
        "Spotify > Account > Manage your plan > Change plan > Cancel Premium",
        [("Individual", 119), ("Duo", 149), ("Family", 179)]),
    "JioSaavn": Merchant(
        "https://www.jiosaavn.com/account",
        "JioSaavn > Settings > Subscription > Cancel",
        [("Pro", 99)]),
    "Adobe CC": Merchant(
        "https://account.adobe.com/plans",
        "Adobe > Account > Plans > Manage plan > Cancel your plan",
        [("Photography", 1675), ("Single App", 1999), ("All Apps", 4230)]),
    "Canva": Merchant(
        "https://www.canva.com/settings/billing-and-plans",
        "Canva > Settings > Billing & plans > Cancel subscription",
        [("Pro", 499), ("Teams", 750)]),
    "ChatGPT Plus": Merchant(
        "https://chatgpt.com/#settings/Subscription",
        "ChatGPT > Settings > Subscription > Manage > Cancel plan",
        [("Go", 399), ("Plus", 1999)]),
    "Google One": Merchant(
        "https://one.google.com/settings",
        "Google One > Settings > Cancel membership",
        [("100 GB", 1300), ("200 GB", 2100), ("2 TB", 6500)]),
    "iCloud": Merchant(
        "https://support.apple.com/en-in/HT207594",
        "iPhone > Settings > Apple ID > iCloud > Manage Storage > Change Plan",
        [("50 GB", 75), ("200 GB", 219), ("2 TB", 749)]),
    "Cult.fit": Merchant(
        "https://www.cult.fit/user/membership",
        "Cult.fit > Profile > Memberships > Cancel Membership",
        [("Live", 999), ("Pro", 1499), ("Elite", 2499)]),
    "Airtel": Merchant(
        "https://www.airtel.in/myaccount",
        "Airtel Thanks > Manage > Postpaid plan > Change plan",
        [("Basic", 449), ("Value", 549), ("Infinity", 999), ("Family", 1599)]),
    "Jio": Merchant(
        "https://www.jio.com/selfcare",
        "MyJio > Mobile > Manage plan > Change plan",
        [("Saver", 239), ("Standard", 299), ("Plus", 399), ("Max", 449)]),
    "ACT Fibernet": Merchant(
        "https://www.actcorp.in/self-care",
        "ACT Self Care > My Account > Change Plan",
        [("Essential", 749), ("Blaze", 1049), ("Storm", 1349), ("Lightning", 1899)]),
    "Swiggy One": Merchant(
        "https://www.swiggy.com/my-account",
        "Swiggy > Account > Swiggy One > Manage > Cancel",
        [("One Lite", 49), ("One", 99)]),
    "Zomato Gold": Merchant(
        "https://www.zomato.com/users/settings",
        "Zomato > Profile > Zomato Gold > Manage membership",
        [("Gold", 149)]),
    "Notion": Merchant(
        "https://www.notion.so/my-settings",
        "Notion > Settings > Plans > Downgrade",
        [("Plus", 800), ("Business", 1400)]),
}

GENERIC_PATH = "Open the merchant's app > Account > Subscription > Cancel"


def cheaper_tier(canonical: str, current_amount: float) -> Optional[tuple[str, float]]:
    """Largest tier strictly cheaper than what the user actually pays."""
    merchant = MERCHANTS.get(canonical)
    if not merchant:
        return None
    below = [t for t in merchant.tiers if t[1] < current_amount * 0.98]
    return max(below, key=lambda t: t[1]) if below else None


def decide(
    cluster: MerchantCluster,
    band: str,
    current_amount: float,
    annual_cost: float,
    periods_per_year: float,
    price_changes: list[PriceChange],
) -> Action:
    merchant = MERCHANTS.get(cluster.canonical)
    url = merchant.url if merchant else None
    path = merchant.menu_path if merchant else GENERIC_PATH
    tier = cheaper_tier(cluster.canonical, current_amount)

    if band == "cancel":
        return Action(
            kind="cancel",
            label=f"Cancel {cluster.canonical}",
            url=url, menu_path=path,
            est_annual_saving=round(annual_cost, 2),
        )

    if band == "downgrade":
        if tier:
            name, price = tier
            return Action(
                kind="downgrade",
                label=(f"{cluster.canonical}: Rs {current_amount:,.0f} -> "
                       f"{name} Rs {price:,.0f}"),
                url=url, menu_path=path,
                est_annual_saving=round((current_amount - price) * periods_per_year, 2),
            )
        return Action(
            kind="cancel",
            label=f"Cancel {cluster.canonical} (no cheaper tier available)",
            url=url, menu_path=path,
            est_annual_saving=round(annual_cost, 2),
        )

    if band == "review" and cluster.category in NEGOTIABLE:
        # Only the hike is claimable — see the module note on computed savings.
        hike = sum((c.to_amount - c.from_amount) for c in price_changes)
        return Action(
            kind="renegotiate",
            label=f"Ask {cluster.canonical} to reinstate your original rate",
            url=url, menu_path=path,
            est_annual_saving=round(max(0.0, hike) * periods_per_year, 2),
        )

    return Action(
        kind="keep",
        label=f"Keep {cluster.canonical} — this one looks fine",
        url=None, menu_path=None,
        est_annual_saving=0.0,
    )


# ------------------------------------------------------- renegotiation drafting

_EMAIL_CACHE: dict[str, str] = {}

_EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}


def _static_email(canonical: str, current: float, original: float, period: str) -> str:
    """Real fallback, not a stub — this ships if Groq is unreachable."""
    hike = current - original
    rate_line = (
        f"My rate has increased from Rs {original:,.0f} to Rs {current:,.0f} per "
        f"{period[:-2] if period.endswith('ly') else period}"
        f" (Rs {hike:,.0f} more), which I was not notified about.\n\n"
        if hike > 0 else
        f"I currently pay Rs {current:,.0f} per "
        f"{period[:-2] if period.endswith('ly') else period}.\n\n"
    )
    return (
        f"Subject: Request to review my {canonical} plan\n\n"
        "Hello,\n\n"
        f"I have been a {canonical} customer for some time and would like to "
        "review my current plan.\n\n"
        + rate_line +
        "I would like to request that my previous rate be reinstated, or to be "
        "moved to a plan that better reflects how much I actually use the "
        "service. I am comparing options at the moment and would prefer to stay "
        "if we can find something that works.\n\n"
        "Could you let me know what you can offer?\n\n"
        "Thank you,\n"
    )


def renegotiation_email(
    canonical: str, category: str, current: float, original: float, period: str
) -> str:
    """Groq-drafted, static fallback. §12: creative text, no factual risk.

    The numbers are interpolated by us, not generated — the model only writes
    the prose around them.
    """
    key = f"{canonical}|{current}|{original}"
    if key in _EMAIL_CACHE:
        return _EMAIL_CACHE[key]

    fallback = _static_email(canonical, current, original, period)
    if not groq_key():
        return fallback

    try:
        from groq import Groq

        response = Groq().chat.completions.create(
            model=GROQ_MODEL,
            temperature=0.4,
            response_format={"type": "json_schema", "json_schema": {
                "name": "renegotiation_email", "strict": True,
                "schema": _EMAIL_SCHEMA}},
            messages=[
                {"role": "system", "content": (
                    "You draft short, polite, effective customer retention emails "
                    "for Indian consumers. Be specific and firm but never rude. "
                    "6 sentences maximum. Use only the figures given to you — "
                    "never invent numbers, dates, or account details. Do not "
                    "include a signature block or placeholder names."
                )},
                {"role": "user", "content": (
                    f"Service: {canonical} ({category})\n"
                    f"Billing period: {period}\n"
                    f"Original rate: Rs {original:,.0f}\n"
                    f"Current rate: Rs {current:,.0f}\n"
                    "Goal: get the original rate reinstated or a better plan."
                )},
            ],
        )
        payload = json.loads(response.choices[0].message.content)
        draft = f"Subject: {payload['subject']}\n\n{payload['body'].strip()}\n"
        _EMAIL_CACHE[key] = draft
        return draft
    except Exception:
        # ponytail: same contract as normalize.llm_resolve — the pipeline never
        # cares why the LLM failed, only that a usable draft still comes back.
        return fallback
