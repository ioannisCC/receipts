<p align="center">
  <img src="assets/logo.svg" width="84" alt="Receipts">
</p>

<h1 align="center">Receipts</h1>

<p align="center"><em>Burden of proof for AI vendor claims.</em></p>

<p align="center">
  Audit the marketing claims of every vendor in an AI product category.<br/>
  In ~90 seconds. For ~$2.
</p>

---

Receipts reads each vendor's homepage, decomposes the marketing copy into atomic outcome claims, hunts the public web for evidence behind each claim, and produces a live credibility leaderboard of the whole market.

The economics matter as much as the result. A cost-aware inference cascade routes every step to the cheapest model that can handle it — small open-weights model for the easy 85%, frontier model only for the 15% the small one isn't confident on. The same sweep run naively against a frontier model alone costs ~10× more and takes ~5× longer.

```
URL ─▶ INGEST ─▶ EXTRACT ─▶ HUNT ─▶ JUDGE ─▶ ADVISE ─▶ HONEST AD ─▶ score ─▶ leaderboard
                  (claims)  (web)  (cascade)  (buyer Qs)  (Magnific)
```

## What a judgment looks like

Every claim gets one of three verdicts. We report **public substantiation**, not truth — the absence of a public receipt is never proof a claim is false.

| Verdict | Meaning |
| --- | --- |
| **Publicly substantiated** | Independent public sources (case studies, third-party reviews, published methodology) corroborate the claim. |
| **Self-reported only** | The claim appears only on the vendor's own surfaces (their site, blog, press releases). |
| **No public receipt** | We searched the public web and could not find a receipt for this claim. |

A vendor's **credibility score** is the weighted average of their judged claims.
A category's **Claim Inflation Index** is how many claims are made on average per claim publicly substantiated — a quiet way to read whether a market is mostly puffery or mostly evidence.

## Architecture

| Stage | Tier | Notes |
| --- | --- | --- |
| **Ingest** | tools | `httpx` + `trafilatura`, falling back to Jina Reader for JS-heavy pages |
| **Extract** | cheap LLM | FActScore-style atomic decomposition of marketing copy into testable claims |
| **Hunt** | tools | Tavily search — receipts are FOUND, never inferred |
| **Judge** | **cascade** | Cheap model issues verdict + confidence; below threshold escalates to the frontier model. This is the routing story. |
| **Advise** | cheap LLM | Buyer questions + recommended next step |
| **Honest ad** | image gen | Magnific Mystic backdrop with the substantiated claims overlaid as DOM text — the image never typesets the figures |

Every external call is wrapped in a telemetry probe that records `{tokens, latency, ttft, cost, escalated}` and streams to the UI over SSE — every number on screen was measured.

## Stack

- **Backend** — Python 3.12 · FastAPI · async pipeline under a semaphore · Pydantic schemas
- **Cheap inference** — Akamai's vLLM-served Qwen3-8B-FP8 (OpenAI-compatible)
- **Frontier inference** — Anthropic Claude Sonnet 4.6
- **Image generation** — Magnific Mystic (Freepik API)
- **Search** — Tavily (with a backup key) · Jina Reader for fallback ingest
- **Cache** — sha256-keyed JSON on disk; re-runs are idempotent
- **Frontend** — Vite + React 18 · single-file App.tsx · serif/glass design language

## Running it

Requires Python 3.12, [`uv`](https://github.com/astral-sh/uv), and Node 18+.

```bash
# Backend
cd backend
uv sync
source .venv/bin/activate
cp ../.env.example ../.env
# Fill in: AKAMAI_INFERENCE_URL, AKAMAI_TOKEN, ANTHROPIC_API_KEY,
#          TAVILY_API_KEY, TAVILY_API_KEY_BACKUP, FREEPIK_API_KEY

# Smoke tests
python scripts/smoke_akamai.py
python scripts/test_evidence.py

# Backend API
uvicorn app.server:app --reload
```

```bash
# Frontend (in another shell)
cd frontend
npm install
npm run dev
# Opens http://localhost:3000
```

The frontend opens on the landing page. Click **Go to demo**, paste vendor names + URLs (or load the example), hit **Audit the market**, and watch the telemetry stream live as each vendor is judged.

## Layout

```
assets/logo.svg                   the mark
backend/app/                      pipeline, schemas, clients, telemetry, server
backend/app/pipeline/             ingest, extract, hunt, judge, advise,
                                  honest_ad, orchestrator
backend/data/vendors/             seed vendor lists per category
backend/scripts/                  smoke + verify scripts
frontend/src/App.tsx              landing + demo views in one file
frontend/src/components/          ReceiptsLogo + a few primitives
frontend/src/index.css            design tokens (OKLCH), glass, aurora,
                                  reveal animations
```

## Why this exists

At single-vendor scale, "check vendor claims against the public web" is a Google search. At market scale — every vendor in a category, every claim on every page, every claim cross-referenced against case studies and reviews — it is only economically possible because the cascade makes inference cheap enough to spend on every claim. That's the thesis.
