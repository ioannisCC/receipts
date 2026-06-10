# Receipts

**Audit the marketing claims of every vendor in an AI product category. In ~90 seconds. For ~$2.**

Receipts reads each vendor's homepage, decomposes their marketing copy into atomic outcome claims, hunts the public web for evidence behind each claim, and produces a live credibility leaderboard of the whole market.

The economics matter as much as the result. A cost-aware inference cascade routes every step to the cheapest model that can handle it — small open-weights model for the easy 85%, frontier model only for the 15% the small one isn't confident on. The same sweep run naively against a frontier model alone costs ~10× more and takes ~5× longer.

```
URL ─▶ INGEST ─▶ EXTRACT ─▶ HUNT ─▶ JUDGE ─▶ ADVISE ─▶ score ─▶ leaderboard
                  (claims)  (web)   (cascade) (buyer Qs)
```

## What a judgment looks like

Every claim gets one of three verdicts. We report public substantiation, not truth.

| Verdict | Meaning |
| --- | --- |
| `SUPPORTED` | Independent public receipts (case studies, third-party reviews) corroborate the claim. |
| `SELF_REPORTED_ONLY` | The claim appears only on vendor-owned surfaces. |
| `NO_PUBLIC_RECEIPT_FOUND` | The claim was searched for and conspicuously absent or contradicted. |

A vendor's **credibility score** is the weighted average of their judged claims. A category's **Claim Inflation Index** is how many claims are made on average per claim actually substantiated.

## Architecture

| Stage | Tier | Notes |
| --- | --- | --- |
| Ingest | tools | `httpx` + `trafilatura`, falling back to Jina Reader for JS-heavy pages |
| Extract | cheap LLM | FActScore-style atomic decomposition |
| Hunt | tools | Tavily search — receipts are FOUND, never inferred |
| Judge | **cascade** | Cheap model issues verdict + confidence; below threshold escalates to frontier model |
| Advise | cheap LLM | Buyer questions + recommended next step |

Every external call is wrapped in a telemetry probe that records `{tokens, latency, ttft, cost, escalated}` and streams to the UI over SSE — every number on screen was measured.

## Stack

- **Backend** — Python 3.12, FastAPI, async pipeline under a semaphore
- **Cheap inference** — Akamai's vLLM-served Qwen3-8B-FP8 (OpenAI-compatible)
- **Frontier inference** — Anthropic Claude Sonnet 4.6
- **Schemas** — Pydantic everywhere; nothing leaves a stage unvalidated
- **Search** — Tavily (with a backup key); Jina Reader for fallback ingest
- **Cache** — sha256-keyed JSON on disk; re-runs are idempotent

## Running it

Requires Python 3.12 and [`uv`](https://github.com/astral-sh/uv).

```bash
cd backend
uv sync
source .venv/bin/activate

cp ../.env.example ../.env
# Fill in: AKAMAI_INFERENCE_URL, AKAMAI_TOKEN, ANTHROPIC_API_KEY, TAVILY_API_KEY

# Smoke the cheap-tier endpoint:
python scripts/smoke_akamai.py

# Smoke the evidence layer:
python scripts/test_evidence.py

# Run the API:
uvicorn app.server:app --reload
```

Then `POST /audit` with a category + vendor list, and stream telemetry from `GET /audit/{run_id}/stream`.

## Layout

```
backend/app/                   pipeline, schemas, clients, telemetry, server
backend/app/pipeline/          ingest, extract, hunt, judge, advise, orchestrator
backend/data/vendors/          seed vendor lists per category
backend/scripts/               smoke + evidence tests
```

## Why this exists

At single-vendor scale, "check vendor claims against the public web" is a Google search. At market scale — every vendor in a category, every claim on every page, every claim cross-referenced against case studies and reviews — it is only economically possible because the cascade makes inference cheap enough to spend on every claim. That's the thesis.
