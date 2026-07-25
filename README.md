# Sieve

Hidden-subscription and recurring-payment leak detector.
Spec / source of truth: [`docs/prd.md`](docs/prd.md).

Deterministic core, LLM at the edges. No database, no persisted financial data.

**Status: feature-frozen.** 188 tests passing.

---

## Does it actually work? (spec §14)

Measured against `ground_truth.json`, which the generator emits *at injection
time* — it records what it planted rather than re-deriving it, so this is a
labelled test set and not a second copy of the detector.

Reproduce with `pytest tests/test_engine.py -s -q`.

| | precision | recall | F1 |
|---|---|---|---|
| **Recurring-transaction detection** | 1.000 | 1.000 | 1.000 |
| **Price-hike detection** | 1.000 | 1.000 | 1.000 |
| **Exclusion accuracy** (rent / EMI / SIP / salary / card / utilities) | 1.000 | 1.000 | 1.000 |
| **Merchant normalization** | 380 / 380 raw strings mapped correctly (100%) | | |

Per profile — 800 transactions each, 18 months:

| profile | subs | hikes | excluded | normalization |
|---|---|---|---|---|
| student | 8/8 | 5/5 | 7/7 | 128/128 |
| young professional | 9/9 | 5/5 | 7/7 | 118/118 |
| family | 9/9 | 5/5 | 7/7 | 134/134 |

### The failures we still have

Perfect scores on a corpus we generated are weaker evidence than they look, and
this is the honest reading of them:

- **Merchant normalization at 100% is close to tautological.** The alias table
  and the generator's templates were authored against the same brand list, so
  this measures that the cascade works — not that it generalises. The real
  measurement is below.
- **Against real-world Indian bank SMS formats the generator never produced,
  the template bank alone scored 0/12.** That is what forced the second
  deterministic tier (field-role extraction), which brings it to **11/12**;
  the LLM fallback recovers the twelfth. The one hard miss is an IMPS transfer
  whose text contains no merchant name at all.
- **Annual subscriptions sit 0.10 above the confidence floor.** Eighteen months
  can hold only two annual charges, so §8's `>= 3` gate is relaxed to 2 for
  them and confidence is capped at 0.60 against a 0.50 floor. A noisier pair
  drops out.
- **The amount-stability gate is unexercised.** Every surviving subscription
  scores 0.0000 against a 0.35 threshold, so that threshold is an assumption,
  not a validated number.
- **SMS parse-rate is deliberately absent from this table.** Our own regexes
  against our own generator is not a measurement.

---

## Run locally

### Backend (FastAPI, port 8000)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Check it: <http://localhost:8000/health> → `{"status":"ok","service":"sieve"}`

macOS / Linux: `source .venv/bin/activate` instead of the Activate.ps1 line.

**Optional LLM (Groq).** Detection works fully without it. Set `GROQ_API_KEY` to
enable merchant naming for strings the alias + fuzzy cascade doesn't recognise;
`GROQ_MODEL` overrides the model (default `openai/gpt-oss-120b`). Every LLM call
has a non-LLM fallback and never blocks the pipeline (spec §2).

### Frontend (Next.js, port 3000)

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. Needs `frontend/.env.local`:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

A green dot on the landing page means the frontend reached the backend.

### Tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest ../tests -q
```

---

## Deploy

Both platforms deploy from a git remote, so GitHub comes first.

### 1. GitHub

```powershell
git init
git add -A
git commit -m "Phase 0: skeleton"
git branch -M main
git remote add origin https://github.com/<you>/sieve.git
git push -u origin main
```

### 2. Backend → Render

1. [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**
2. Pick the repo. Render reads [`render.yaml`](render.yaml) — no manual config.
3. Wait for green, then check `https://sieve-api-XXXX.onrender.com/health`.

Free tier sleeps after ~15 min idle; the first request takes ~50s to wake.

### 3. Frontend → Vercel

1. [vercel.com/new](https://vercel.com/new) → import the repo
2. **Root Directory: `frontend`** ← the only setting Vercel cannot infer
3. Environment variable: `NEXT_PUBLIC_API_URL` = the Render URL (no trailing slash)
4. Deploy

### 4. Verify like a judge

Open the Vercel URL **on a phone, on mobile data** — not the machine that built it.
Green dot = both halves are live and talking.

---

## Layout

```
backend/models.py     frozen interface (spec §5) — the whole team codes against this
backend/main.py       FastAPI app + /health
data/                 demo profiles + ground truth (Phase 1)
tests/                interface + detection tests
docs/prd.md           the spec
render.yaml           backend deploy config
```

### A note on `models.py`

Spec §5 is implemented field-for-field, plus three additions it needs to be usable:

- **`Action`** — §5 annotates `Subscription.action: "Action"` but never defines the type.
  Shape derived from §12.
- **`ExcludedCluster`** — §15's "correctly excluded" panel needs a reason per reject.
- **`Subscription.next_charge_date`** — §15's dashboard table has a "next charge" column.

No §5 field was renamed or removed. Treat the file as frozen; `tests/test_models.py`
fails loudly if it drifts.
