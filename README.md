# Sieve

Hidden-subscription and recurring-payment leak detector.
Spec / source of truth: [`docs/prd.md`](docs/prd.md).

Deterministic core, LLM at the edges. No database, no persisted financial data.

**Status: Phase 0** — deployable skeleton + frozen data model. No detection logic yet.

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
