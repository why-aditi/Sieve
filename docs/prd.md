# LeakLens — Hidden Subscription & Recurring Payment Leak Detector

**InnovaHack Chapter 1 · Domain 1: FinTech · Problem Statement 1**
Build window: 25 July 2026, 10:00 → 26 July 2026, 10:00 IST
Deliverables: deployed URL + 6–7 slide PPT + optional 5-min video

---

## 1. The pitch

> Point it at your inbox and your bank SMS. In 30 seconds it tells you: *"You're leaking ₹4,240/month across 7 subscriptions. Three raised their prices without telling you. Here's exactly what to cancel and how."*

Everything in this document exists to make that sentence true and demonstrable to a judge who will never speak to us.

**Positioning line for slide 2:**
*"Nobody downloads a CSV. Everyone has 5,000 bank messages sitting on their phone and in their inbox — we read the ones that matter, and only those."*

---

## 2. Design principles

These are the decisions that separate this from the other submissions. Do not relax them under time pressure.

**Deterministic core, LLM at the edges.** Recurrence detection is arithmetic on dates. It runs in 200ms, costs nothing, and returns the same answer every time. The LLM is used for exactly three things: naming unrecognised merchants, parsing SMS/email bodies that fail regex, and drafting renegotiation emails. All three fail gracefully to a non-LLM fallback. Competing teams will pipe the whole statement into an LLM and ask it to find subscriptions — that hallucinates amounts, misses charges, and dies when the API rate-limits at 4 AM.

**Every number on screen is computed and explainable.** The leak score is a visible weighted formula with a "why this score" breakdown per row. No LLM-emitted confidence numbers.

**The judge must see value in 10 seconds with zero data of their own.** The demo path is one click, always works, never touches the network for auth.

**Say no loudly.** Rent, EMIs, SIPs and salary credits are perfectly periodic and are *not* leaks. Correctly excluding them is a feature we show, not a bug we hide.

**Never persist raw financial data.** Session-only, in-memory, discarded on tab close. This is real bank data.

---

## 3. Scope and hard constraints

### 3.1 What we are building

A web app with four ingestion adapters feeding one detection engine and one dashboard.

### 3.2 Constraints that are non-negotiable facts

| Constraint | Consequence |
|---|---|
| **A web app cannot read SMS.** No browser API exists. Web OTP API surfaces a single OTP-formatted message, user-initiated, no history access. Android `READ_SMS` is restricted to the default SMS handler + a narrow Play Store exemption list. | The "SMS permission" card at signup must resolve to an *import sheet* (paste / XML upload), not an OS permission grant. Design around this openly. |
| **Gmail `gmail.readonly` is a restricted scope.** Production use requires Google verification + CASA security assessment — weeks. Unverified apps run in testing mode: 100 manually-added test users; everyone else sees the "this app isn't verified" interstitial. | Real OAuth works on *our* accounts and appears in the video. A judge cannot use it. Every Gmail card ships with a **"Try with demo account"** button beside it. |
| **Async judging.** No live demo, no Q&A. | Legibility beats sophistication. The deployed URL and the video carry all the explanation. |
| **~20 usable hours.** | Feature freeze at hour 19 is a hard rule, not a target. |

### 3.3 Explicit non-goals

- Actually cancelling subscriptions on the user's behalf (we generate the deep link + script; we do not automate the click)
- Bank aggregator / Account Aggregator framework integration
- Multi-user accounts, persistence, login history
- Mobile native app
- PDF statement parsing (stretch only — Indian bank PDF layouts will eat four hours)

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────┐
│  INGESTION ADAPTERS                                     │
│  DemoAdapter · SmsPasteAdapter · SmsXmlAdapter ·        │
│  GmailAdapter · CsvAdapter                              │
└───────────────────────┬─────────────────────────────────┘
                        │  all emit Transaction[]
                        ▼
┌─────────────────────────────────────────────────────────┐
│  DEDUP  (same txn from email + SMS)                     │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│  MERCHANT NORMALIZATION                                 │
│  regex clean → alias dict → fuzzy → LLM fallback        │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│  CLUSTER by canonical merchant                          │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌──────────────────┬──────────────────┬───────────────────┐
│ RECURRENCE       │ PRICE CHANGE     │ DORMANCY          │
│ detection        │ detection        │ inference         │
└──────────────────┴────────┬─────────┴───────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  EXCLUSION FILTER  (rent, EMI, SIP, salary, CC bill)    │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│  LEAK SCORING  →  ACTION ENGINE  →  DASHBOARD           │
└─────────────────────────────────────────────────────────┘
```

The adapter boundary is the whole point: adding a source later costs an afternoon, not a rewrite. Say this on the architecture slide.

---

## 5. Data model

```python
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

@dataclass
class Transaction:
    date: date
    merchant_raw: str          # "UPI/NETFLIX BILLDESK/928471/PAYMENT"
    amount: float              # always positive
    direction: Literal["debit", "credit"]
    source: Literal["demo", "sms_paste", "sms_xml", "gmail", "csv"]
    source_ref: Optional[str]  # message id / row index, for the audit trail
    account_hint: Optional[str] # "XX4471"

@dataclass
class MerchantCluster:
    canonical: str             # "Netflix"
    category: str              # "streaming"
    raw_variants: list[str]    # the 4 strings that collapsed into this
    transactions: list[Transaction]

@dataclass
class Subscription:
    cluster: MerchantCluster
    period: Literal["weekly", "monthly", "quarterly", "annual"]
    period_days: float
    confidence: float          # 0-1, from regularity + anchoring
    current_amount: float
    annual_cost: float
    price_changes: list["PriceChange"]
    dormancy_signals: list[str]
    leak_score: float          # 0-100
    score_breakdown: dict[str, float]
    action: "Action"

@dataclass
class PriceChange:
    from_amount: float
    to_amount: float
    changed_on: date
    pct: float
    annual_impact: float
    kind: Literal["step", "creep"]
```

---

## 6. Ingestion adapters

### 6.1 Adapter interface

```python
class IngestionAdapter(Protocol):
    source_name: str
    def fetch(self, payload) -> list[Transaction]: ...
```

Five implementations, one interface. Nothing downstream knows or cares which ran.

### 6.2 DemoAdapter — build this first, it is the judge's path

Three pre-built profiles loaded from bundled JSON: **Student**, **Young professional**, **Family**.

One click, no network, no auth, cannot fail. If a judge only ever presses one button, this is it. Make the button visually primary on the landing page.

### 6.3 SmsPasteAdapter — the hero feature

UX: a single textarea. *"Open Messages → filter to your bank → select all → copy → paste here."* Fifteen seconds of user effort, zero permissions.

Indian bank SMS is aggressively templated. Roughly 12 regex patterns cover the field:

```python
SMS_PATTERNS = [
    # HDFC
    r"Rs\.?(?P<amt>[\d,]+\.?\d*)\s+debited from a/c\s+(?P<acct>[X\d]+)\s+on\s+(?P<date>[\d\-/]+)\s+to\s+(?P<merch>.+?)\s+via",
    # ICICI card
    r"INR\s+(?P<amt>[\d,]+\.?\d*)\s+spent on\s+.*?Card\s+(?P<acct>[X\d]+)\s+at\s+(?P<merch>.+?)\s+on\s+(?P<date>[\w\-]+)",
    # SBI ACH mandate
    r"Rs\.?\s?(?P<amt>[\d,]+\.?\d*)\s+debited towards\s+(?P<merch>.+?)\s+on\s+(?P<date>[\d/\-]+)",
    # Axis UPI
    r"Rs\s?(?P<amt>[\d,]+\.?\d*)\s+debited.*?UPI/(?P<merch>[A-Z0-9]+)/.*?on\s+(?P<date>[\d\-]+)",
    # Kotak / PNB / BoB / generic UPI app receipts ...
]

BANK_SENDERS = {"HDFCBK","ICICIB","SBIINB","AXISBK","KOTAKB","PNBSMS",
                "BOBTXN","CANBNK","IDFCFB","YESBNK","INDUSB","AUBANK"}
```

Unmatched lines batch into **one** LLM call returning structured JSON. This is a reformatting task on text the model can see — low hallucination risk. Cap the batch; if it fails, drop the unmatched lines and report the count honestly in the scan receipt.

### 6.4 SmsXmlAdapter — the high-volume path

**SMS Backup & Restore** is already installed on a large share of Indian phones and exports the full message history as XML. Accepting that file *is* our "connect SMS" — one file picker, 5,000 real bank messages in one shot.

```python
import xml.etree.ElementTree as ET

def fetch(self, file) -> list[Transaction]:
    out = []
    for sms in ET.parse(file).getroot().iter("sms"):
        body   = sms.get("body")
        sender = sms.get("address", "")
        ts     = int(sms.get("date")) / 1000
        if not is_bank_sender(sender):     # VM-HDFCBK, AD-ICICIB, JD-SBIINB
            continue
        txn = parse_sms_body(body, ts)     # same parser as paste adapter
        if txn:
            out.append(txn)
    return out
```

Same parser behind both SMS adapters. Sender IDs carry a carrier prefix (`VM-`, `AD-`, `JD-`, `BP-`) — strip it before matching.

### 6.5 GmailAdapter — real, but gated

Scope: `https://www.googleapis.com/auth/gmail.readonly`.

Query, scoped hard:

```
(from:(hdfcbank.net OR icicibank.com OR sbi.co.in OR axisbank.com OR
       kotak.com OR paytm.com OR phonepe.com OR razorpay.com) OR
 subject:("payment successful" OR receipt OR invoice OR "subscription renewed"))
 newer_than:18m
```

Pull `snippet` and the `text/plain` MIME part only. **Never open attachments** — say so in the consent copy. Regex first (same pattern bank), LLM fallback on unparsed bodies, batched.

Token handling: session-only, held in memory, **no refresh token persisted**. A hackathon project holding live Gmail tokens for bank mail is a genuine liability, not a hypothetical one.

Beside the Connect button, always: **"Try with demo account"** → loads a pre-scanned mock Gmail result set through the identical streaming UI. This is what the judge presses.

### 6.6 CsvAdapter — cheap fallback

Expected columns: `date, description, amount, type`. ~30 lines with pandas. Column-name fuzzy matching so slight header variations don't break it. Keep it — it costs almost nothing and covers the judge who happens to have a statement.

### 6.7 Dedup

Multi-source means the same charge arrives twice (email receipt + bank SMS). Match on:

- amount within ±₹1
- date within 24 hours
- merchant fuzzy ratio > 80

Keep the record with the richer merchant string; retain both `source_ref`s for the audit trail. Mention this on the architecture slide — it's a detail that only appears when multi-source ingestion is genuinely built.

---

## 7. Merchant normalization — the technical moat

This is the hard part and it is where the demo lives. The same merchant appears as:

```
UPI/NETFLIX BILLDESK/928471/PAYMENT
ACH-D- NETFLIX ENTERTAINMENT SERVICES
NEFT-NETFLIXENT-8821-RTGS
POS 4471XXXX2210 NETFLIX.COM MUMBAI
```

Four strings, one subscription. Naive grouping yields four "subscriptions" of one charge each and detects nothing. **Slide 3 is these four lines collapsing into one row** — it makes the difficulty legible in two seconds.

### Cascade, cheapest first

**Step 1 — Regex cleanup**

```python
NOISE = [
    r"^(UPI|ACH[-\s]?D?|NEFT|IMPS|RTGS|POS|ATM|MANDATE|ECS|NACH)[-/\s]*",
    r"\b\d{4,}\b",                      # reference / card digit runs
    r"\b(PVT|PRIVATE|LTD|LIMITED|INDIA|IN|SERVICES|ENTERTAINMENT|TECHNOLOGIES)\b",
    r"\.(COM|IN|CO|NET)\b",
    r"\b(MUMBAI|DELHI|BANGALORE|BENGALURU|PUNE|HYDERABAD|CHENNAI|KOLKATA|GURGAON|NOIDA)\b",
    r"[^A-Z0-9\s]",
]
def clean(s): 
    s = s.upper()
    for p in NOISE: s = re.sub(p, " ", s)
    return re.sub(r"\s+", " ", s).strip()
```

**Step 2 — Alias dictionary.** Hand-build ~60 entries. Thirty minutes of typing, enormous accuracy payoff.

```python
ALIASES = {
  "NETFLIX": ("Netflix", "streaming"),
  "SPOTIFY": ("Spotify", "music"),
  "HOTSTAR": ("JioHotstar", "streaming"),
  "DISNEY": ("JioHotstar", "streaming"),
  "PRIMEVIDEO": ("Amazon Prime", "streaming"),
  "AMAZONPRIME": ("Amazon Prime", "streaming"),
  "JIOSAAVN": ("JioSaavn", "music"),
  "GAANA": ("Gaana", "music"),
  "ZEE5": ("Zee5", "streaming"),
  "SONYLIV": ("SonyLIV", "streaming"),
  "YOUTUBEPREMIUM": ("YouTube Premium", "streaming"),
  "GOOGLEONE": ("Google One", "cloud"),
  "ICLOUD": ("iCloud", "cloud"),
  "ADOBE": ("Adobe CC", "saas"),
  "CANVA": ("Canva", "saas"),
  "NOTION": ("Notion", "saas"),
  "FIGMA": ("Figma", "saas"),
  "OPENAI": ("ChatGPT Plus", "saas"),
  "CULTFIT": ("Cult.fit", "fitness"),
  "SWIGGYONE": ("Swiggy One", "food"),
  "ZOMATOGOLD": ("Zomato Gold", "food"),
  "AIRTEL": ("Airtel", "telecom"),
  "JIO": ("Jio", "telecom"),
  "ACTFIBER": ("ACT Fibernet", "telecom"),
  # ... target 60
}
```

**Step 3 — Fuzzy match.** `rapidfuzz.token_set_ratio(cleaned, alias) > 85` catches typos and variants.

**Step 4 — LLM fallback.** Collect everything still unmatched, send in **one batched call**:

> "For each merchant string, return canonical brand name and category from [streaming, music, saas, cloud, fitness, telecom, food, insurance, utility, other]. JSON array only, no prose."

Cache by cleaned string. On failure, fall back to the cleaned string with category `other` and continue — never block the pipeline on the LLM.

---

## 8. Recurrence detection

Group by canonical merchant, sort by date, compute inter-arrival deltas in days.

**Hard gate: require ≥3 occurrences.** Two charges are a coincidence.

```python
def detect_recurrence(txns):
    if len(txns) < 3: return None
    dates  = sorted(t.date for t in txns)
    deltas = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
    med    = statistics.median(deltas)

    period = snap_to_period(med)          # weekly 7±2, monthly 28-32,
    if period is None: return None        # quarterly 88-95, annual 355-370

    # Signal A: regularity
    mad        = statistics.median([abs(d - med) for d in deltas])
    regularity = max(0.0, 1.0 - (mad / med) * 3)

    # Signal B: day-of-month anchoring  ← the trick most teams miss
    doms   = [d.day for d in dates]
    anchor = 0.0
    if period == "monthly":
        centre = statistics.median(doms)
        spread = statistics.median([abs(x - centre) for x in doms])
        anchor = max(0.0, 1.0 - spread / 4)

    confidence = max(regularity, anchor)
    return period, med, confidence
```

**Why anchoring matters:** monthly subscriptions drift a day or two around weekends and month lengths, so raw deltas look noisy (30, 31, 28, 31 → MAD looks bad relative to short months). But if every charge lands on day 14 ± 2, that's strong independent evidence. Taking `max()` of the two signals recovers subscriptions that pure delta-regularity rejects.

**Amount stability:** compute *per price segment* (see §9), never across the whole series. Otherwise a genuine price hike registers as irregularity and you reject a real subscription — a bug that will silently halve your recall.

### 8.1 Exclusion filter — the slide nobody else has

These are perfectly periodic and are **not** subscription leaks:

| Excluded | Detection heuristic |
|---|---|
| Rent | monthly, amount > ₹5,000, merchant matches person-name pattern or `RENT` |
| Salary credit | `direction == credit`, monthly, large |
| EMI / loan | keywords `EMI`, `LOAN`, `HDFCLOAN`, `BAJAJFIN`; fixed amount, monthly |
| SIP / investment | keywords `SIP`, `MF`, `GROWW`, `ZERODHA`, `KUVERA`, `NIPPON` |
| Credit card bill | keywords `CC PAYMENT`, `CARD PAYMENT`, `AUTOPAY`; variable amount |
| Utilities | electricity / water / gas boards — periodic but variable amount |

Then **show the rejects list in the UI and on slide 6**: *"6 recurring payments correctly excluded."* Every competing demo will confidently flag the user's rent as a subscription to cancel.

---

## 9. Price change detection

Within each cluster, walk the amount series looking for a **step that persists**:

```python
def detect_price_changes(txns, threshold=0.05, persist=2):
    changes, series = [], [(t.date, t.amount) for t in sorted(txns, key=lambda x: x.date)]
    i = 0
    while i < len(series) - persist:
        cur, nxt = series[i][1], series[i+1][1]
        if abs(nxt - cur) / cur > threshold:
            following = [a for _, a in series[i+1 : i+1+persist]]
            if all(abs(a - nxt) / nxt < 0.02 for a in following):   # it held
                changes.append(PriceChange(
                    from_amount=cur, to_amount=nxt, changed_on=series[i+1][0],
                    pct=(nxt-cur)/cur*100,
                    annual_impact=(nxt-cur) * periods_per_year,
                    kind="step"))
                i += persist
        i += 1
    return merge_creep(changes)
```

Persistence is what separates a real hike from a one-off (extra device, partial-month proration, GST rounding).

Report it human-scale:

> **Spotify: ₹119 → ₹149 in March 2026.** No email, no notification. That's **₹360/year** you didn't agree to.

**Creep detection:** three hikes of 8% each over eighteen months is a different and more irritating story than one big jump. If ≥3 changes, all same-direction, cumulative > 15% → mark as `creep` and report the total.

---

## 10. Dormancy inference — be honest about this

**You cannot see usage from a bank statement.** Teams will either ignore this requirement or fake it. Use inferable proxies and label them as proxies in the UI.

| Signal | Detection |
|---|---|
| **Redundancy** | ≥2 active subscriptions in the same category (two music services, three streamers, gym + fitness app) |
| **Trial conversion** | ₹0 or ₹1 charge followed by full price — classic forgotten signup |
| **Silent annual renewal** | large annual charge, no related activity in surrounding weeks |
| **Zombie** | subscription-category merchant with no engagement signal anywhere in the statement |

Then add **one tap per subscription in the dashboard**: *"Used it this month? Yes / No / Can't remember."* Ten minutes of build. It's honest, it makes the app interactive for a judge with no data of their own, and it feeds the score. **"Can't remember" is itself a strong dormancy signal** — call that out in the video, it's a nice detail.

---

## 11. Leak scoring — computed, not vibes

Every other team's score will be an LLM emitting a number. Ours is arithmetic we display.

```python
leak_score = 100 * (
    0.35 * cost_weight        # annual cost ÷ total subscription spend, capped at 1
  + 0.25 * dormancy           # 0-1 from §10 signals + user tap
  + 0.20 * redundancy         # 1.0 if a same-category duplicate exists
  + 0.15 * unnoticed_hike     # 1.0 if a price change was detected
  + 0.05 * cheaper_tier       # 1.0 if a known cheaper tier exists
)
```

Weights are tunable — what matters is that they're **visible**. Every row gets a **"why this score"** expander showing each term's contribution as a small stacked bar. Twenty minutes of work; it covers the transparency criterion completely.

**Portfolio score** = spend-weighted mean of subscription scores, displayed as one number beside the monthly rupee figure.

Bands: 0–30 Keep · 31–60 Review · 61–80 Downgrade · 81–100 Cancel.

---

## 12. Action engine

The brief asks for a *concrete action plan*. Most submissions will output the word "cancel."

| Action | What we produce |
|---|---|
| **Cancel** | Deep link to the cancellation page **+ exact menu path**: `Netflix → Account → Membership → Cancel Membership`. Pre-written lookup table for the top 20 merchants — a dict, not intelligence. |
| **Downgrade** | Named tier + delta: *"Netflix Premium ₹649 → Standard ₹499. You've never had more than one device streaming."* Static tier table for major services. |
| **Renegotiate** | LLM-drafted email or phone script for gyms, ISPs, insurance. Good LLM use: creative text, no factual risk. |
| **Keep** | Say so explicitly. A tool that flags everything is a tool nobody trusts. |

**Top of the dashboard, largest element on the page:**

> ### Act on all recommendations → save ₹18,400/year

That's the number that ends up in the judge's memory.

---

## 13. Synthetic data generator — build in hour 2

18 months, ~800 transactions per profile. This is simultaneously the demo data and the labelled test set.

```
Real subscriptions (7-9):
  Netflix ₹649 monthly · Spotify ₹119→₹149 monthly (HIKE)
  JioHotstar ₹299 quarterly · Cult.fit ₹1,499 monthly
  Adobe CC ₹1,675 monthly · Google One ₹1,300 annual (SILENT RENEWAL)
  Amazon Prime ₹1,499 annual · JioSaavn ₹99 monthly (REDUNDANT with Spotify)
  ChatGPT Plus ₹1,999 monthly (TRIAL ₹0 → full price)

Format variety: cycle 3-4 raw string templates per merchant
Decoys (must be excluded): rent ₹18,000 · salary credit · 2 EMIs
                           · SIP ₹5,000 · credit card autopay
Noise (400+): Swiggy, Zomato, Amazon retail, fuel, UPI-to-friends,
              ATM withdrawals, IRCTC, Uber
Injected: 2 step hikes · 1 creep (3× 8%) · 1 trial conversion
          · 1 forgotten annual renewal · 1 redundant pair
```

Emit `ground_truth.json` alongside. You now have a labelled test set for free — that becomes slide 6.

Also emit the **same data rendered as SMS text and as email HTML**, so every adapter has something real to parse and the dedup path is exercised.

---

## 14. Evaluation harness — the slide that wins it

Twenty minutes of work. Ten other teams will have a dashboard; one will have measured whether it's right.

```python
def evaluate(detected, ground_truth):
    tp = len(detected & ground_truth)
    fp = len(detected - ground_truth)
    fn = len(ground_truth - detected)
    return {
        "precision": tp / (tp + fp),
        "recall":    tp / (tp + fn),
        "f1":        2*tp / (2*tp + fp + fn),
    }
```

Report separately:
- **Recurring-transaction detection:** precision / recall / F1 across all three profiles
- **Merchant normalization accuracy:** % of raw strings mapped to correct canonical
- **Price-hike detection:** how many of the injected hikes were caught, and false alarms
- **Exclusion accuracy:** were rent / EMI / SIP correctly kept out
- **The failures we still have.** Name them. Honesty about a known false positive reads as competence, not weakness.

---

## 15. UI specification

### Screen 1 — Landing

Headline: **"You're probably leaking ₹4,000 a month. Find out in 30 seconds."**
Primary button: **See it with sample data** (loads DemoAdapter instantly).
Secondary: *Connect your own →* (goes to Screen 2).
Below the fold: the four-Netflix-strings visual, the privacy line.

### Screen 2 — Permissions / connect

Three independently grantable cards:

| Card | Button behaviour | Judge-usable |
|---|---|---|
| **Email** | Real Google OAuth · + "Try with demo account" | via demo button |
| **SMS** | Opens import sheet: paste textarea / XML upload | yes |
| **Statement** | CSV upload | yes |

Consent copy shown **before** any grant:

> We read messages from 40 known bank senders only. We never open attachments. Nothing is stored — your data is parsed in memory and discarded when you close this tab.

### Screen 3 — Scanning

Live-streaming list of found transactions with source badges. This screen *looks* like autonomous ingestion regardless of which adapter fed it — it is the visual centrepiece of the video.

Ends with a **"what we read" receipt**:

> Scanned 4,182 messages · 340 from bank senders · 3,842 ignored · 0 attachments opened · 0 bytes stored

A judge sees that and reads it as a team that thought about handling other people's bank data.

### Screen 4 — Dashboard

- **Hero:** ₹4,240/month leaking · portfolio leak score · "save ₹18,400/year"
- **Subscription table:** merchant · amount · period · next charge · leak score · action badge. Row expands into: score breakdown bars, price history sparkline, raw-variant list ("we matched 4 different descriptions"), the used-it-this-month tap, the cancellation path.
- **Price hikes panel:** before/after with annual impact
- **Category donut:** spend by category
- **Correctly excluded panel:** rent, EMIs, SIP, salary — with the reason each was excluded

---

## 16. Privacy & consent engineering

The instinct is one big "scan my email and SMS" button. Resist it — scoping the request is simultaneously better product, better ethics, and a better slide.

Back the copy with real engineering, because it's easier than the alternative:

- No OAuth refresh token persisted; access token in memory, session-scoped
- No raw message or transaction written to any database
- All parsing client-side where possible; if server-side, request-scoped only
- A **real** "delete everything" button
- Attachments never fetched, and the consent screen says so

Slide-worthy line: *"Your bank data never leaves your session. We can prove it — there's no database."*

---

## 17. Stack

| Layer | Choice | Fallback if behind |
|---|---|---|
| Frontend | Next.js + Tailwind + Recharts, Vercel | **Streamlit, single file** |
| Backend | FastAPI on Render (free tier) | fold into Streamlit |
| Parsing | pandas, rapidfuzz, python-dateutil, lxml | — |
| LLM | one batched call per stage, cached | skip entirely, use cleaned strings |

**Hard rule: if the detection engine isn't working by hour 12, the UI is Streamlit and there is no discussion.** A working Streamlit app beats a beautiful Next.js shell with no engine behind it.

**Deploy a hello-world in the first hour, before writing any logic.** The deployed-URL requirement is where teams die at 9:50 AM, and the guidelines state that incomplete or inaccessible submissions may be disqualified.

---

## 18. Schedule

| Hours | Work | Owner |
|---|---|---|
| 0–1 | Repo, CI, **hello-world deployed and reachable from another device** | all |
| 1–3 | Synthetic data generator + ground truth + SMS/email renderings | Data |
| 3–6 | Merchant normalization cascade | Core |
| 6–9 | Recurrence + price-change detection | Core |
| 9–11 | Exclusion filter, leak scoring, action lookup table | Core |
| 11–13 | Signup/permissions screen · SMS paste + XML adapters wired | Front |
| 13–15 | Gmail OAuth — **only if the engine is done** | Front |
| 15–19 | Dashboard, scan-streaming screen, polish | Front |
| 17–19 | Evaluation harness, fix worst failures | Data |
| **19** | **CODE FREEZE. Deploy. Test live URL on someone else's phone.** | all |
| 19–22 | Slides | all |
| 22–23 | Video | all |
| 23–24 | Submit — with an hour of buffer | Leader |

### Kill switches

- **Hour 13:** recurrence detection shaky → cut Gmail OAuth. Permission card stays, greyed, "coming soon." The video shows the SMS path doing real work.
- **Hour 15:** UI behind → drop to Streamlit, keep every algorithm.
- **Hour 17:** anything unfinished → cut features, never cut the evaluation slide.
- **Hour 19:** freeze regardless of state. Slides and video always take longer than anyone budgets, and the video is the only channel where you explain your reasoning to a judge who will never speak to you.

---

## 19. Task split (adjust to headcount)

**Core / algorithms** — normalization cascade, recurrence, price change, scoring. The heart. Give this to the strongest Python person.

**Data / eval** — synthetic generator, ground truth, evaluation harness, slide 6. Underrated; this is the differentiator.

**Frontend** — landing, permissions, scan stream, dashboard. Starts on static mock data at hour 3; does not wait for the engine.

**Integration / deploy** — adapters, OAuth, deployment, keeping the live URL green. Owns the submission checklist.

Interface contract is frozen at hour 3: everyone codes against the `Transaction` and `Subscription` dataclasses in §5 so nobody blocks on anybody.

---

## 20. Slides (6–7)

1. **The leak** — ₹4,240/month, statement screenshot, the emotional hook
2. **Why nobody solves it** — nobody exports CSVs; the data lives in SMS and email. The four-Netflix-strings problem.
3. **How it works** — the §4 pipeline diagram, with *"deterministic core, LLM at the edges"* stated outright
4. **The catch** — silent price hike, before/after, ₹360/year
5. **The action plan** — cancel/downgrade/renegotiate with real menu paths + "save ₹18,400/year"
6. **Does it actually work** — precision/recall table, the correctly-excluded list, the known failures
7. *(optional)* **Privacy + roadmap** — no database, session-only; next: Account Aggregator, auto-cancel

---

## 21. Video script (5 min)

| Time | Beat |
|---|---|
| 0:00–0:20 | The problem, one sentence, over a cluttered statement |
| 0:20–0:50 | Landing → "See it with sample data" → dashboard appears. Show the money number. |
| 0:50–1:30 | The four Netflix strings collapsing. Explain why this is the hard part. |
| 1:30–2:10 | Price hike panel. Spotify ₹119→₹149. Nobody told you. |
| 2:10–2:50 | Expand a row: score breakdown, cancellation path, "used it this month?" |
| 2:50–3:30 | Correctly excluded panel — rent, EMI, SIP. "We don't tell you to cancel your rent." |
| 3:30–4:10 | **Real Gmail OAuth on our own account**, live, 15 seconds. Then SMS paste, real messages. |
| 4:10–4:40 | Evaluation numbers on screen |
| 4:40–5:00 | Privacy: no database. Close on the savings number. |

---

## 22. Submission checklist

- [ ] Deployed URL live and tested **from a different device and network**
- [ ] Demo button works with no auth, no upload, no network dependency
- [ ] Google Form submitted by **team leader only**
- [ ] Drive link set to **"Anyone with the link can view"** — verify in incognito
- [ ] PPT 6–7 slides, exported as PDF as well
- [ ] Video uploaded and playable in incognito
- [ ] Team name, leader name, all members, **track = FinTech PS1** stated in the form
- [ ] Submitted by **09:00 IST**, not 09:55

---

## 23. Risk register

| Risk | Mitigation |
|---|---|
| Gmail OAuth eats the day | Hard cut at hour 13; demo button always present |
| LLM API down / rate-limited at 4 AM | Every LLM step has a non-LLM fallback; detection never depends on it |
| Render free tier cold-start makes the URL look broken | Ping every 10 min from a cron; or go fully static/client-side |
| Merchant normalization underperforms on real SMS | Alias dictionary is the floor — expand it, it's just typing |
| Deployment fails at hour 23 | Deployed at hour 1 and kept green all night |
| Team disagrees about scope at hour 15 | Kill switches in §18 are pre-agreed, not negotiated live |