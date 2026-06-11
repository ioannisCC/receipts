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

Every external call is wrapped in a telemetry probe that records `{stage, model, tokens, latency, ttft, cost, escalated}` and streams to the UI over SSE. The dashboard shows both model attempts and tool attempts:

- **Qwen / Akamai** — cheap-tier model attempts, including no-response attempts
- **Claude Sonnet 4.6** — frontier model calls and token spend
- **Tavily** — public web search attempts for receipts
- **Page scrape** — vendor page ingest attempts

The top-line dollar number is **LLM spend**: token cost for models plus a small imputed infrastructure cost for cheap-tier attempts. Tool pricing, such as Tavily subscription or search billing, is displayed as attempted but not priced unless explicitly modeled.

## Stack

- **Backend** — Python 3.12 · FastAPI · async pipeline under a semaphore · Pydantic schemas
- **Cheap inference** — Akamai's vLLM-served Qwen3-8B-FP8 (OpenAI-compatible)
- **Frontier inference** — Anthropic Claude Sonnet 4.6
- **Image generation** — Magnific Mystic (Freepik API)
- **Search** — Tavily (with a backup key) · Jina Reader for fallback ingest
- **Cache** — sha256-keyed JSON on disk; re-runs are idempotent
- **Frontend** — Vite + React 18 · single-file App.tsx · serif/glass design language

## Features

### Claim auditing

- Scrapes vendor websites and converts pages into readable text
- Extracts specific, measurable marketing claims
- Ignores vague copy like "best-in-class" unless there is a concrete outcome
- Searches for public receipts behind each claim
- Judges claims as publicly substantiated, self-reported only, or no public receipt
- Shows confidence, rationale, and source URLs for each judgment

### Market scoring

- Calculates a vendor credibility score from judged claims
- Shows verdict breakdown per vendor
- Computes the Claim Inflation Index: claims made per substantiated claim
- Ranks vendors into a live credibility leaderboard
- Groups public evidence and web sources for inspection
- Generates buyer due-diligence questions and a recommended next step

### Model routing

- Attempts the cheap Qwen/Akamai model first when cascade mode is enabled
- Escalates to Claude when the cheap model fails, times out, or is uncertain
- Supports Claude-only fallback mode for reliable demos
- Records Qwen no-response attempts instead of hiding them
- Applies a small imputed cost to cheap-tier attempts so Qwen usage is visible
- Separates successful token-generating calls from no-response attempts

### Tool visibility

- Shows Tavily search attempts separately from model calls
- Shows page scrape attempts separately from model calls
- Displays tool attempts even when tool pricing is not modeled
- Keeps LLM spend separate from unpriced tool/subscription cost
- Streams telemetry live through Server-Sent Events
- Writes run telemetry to JSONL logs for replay/debugging

### Demo dashboard

- Live top-bar telemetry for spend, elapsed time, calls, re-checks, and progress
- Model/tool breakdown such as:

  ```text
  Claude Sonnet 4.6 model · 8 attempts · $0.0399
  Qwen 3 model · 10 attempts · 10 no response · $0.0020
  Tavily search tool · 8 attempts · pricing not tracked
  ```

- Expandable vendor cards with claims, sources, and buyer questions
- Custom vendor input: one `Name, https://url.com` per line
- Preset demo examples for AI support agents and AI SDRs
- Fast-fail timeout controls so broken cheap endpoints do not freeze the UI

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

# Useful demo knobs:
# CHEAP_FALLBACK_TO_PREMIUM=true   # reliable Claude-only fallback mode
# CHEAP_FALLBACK_TO_PREMIUM=false  # cascade mode: Qwen first, Claude on failure/low confidence
# CHEAP_ATTEMPT_COST_USD=0.0002    # imputed visible cost per cheap-tier attempt
# CHEAP_LLM_TIMEOUT_S=6            # fail fast if the cheap endpoint hangs

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

## Demo script

Use this for a 3-minute walkthrough:

1. **Problem** — AI vendors make bold claims, but buyers need public proof before trusting them.
2. **Input** — Paste a vendor such as:

   ```text
   Intercom Fin, https://www.intercom.com/fin
   ```

3. **Pipeline** — Receipts reads the page, extracts measurable claims, searches the web with Tavily, judges each claim, and generates buyer questions.
4. **Telemetry** — The top bar shows every model and tool attempt. If Qwen is attempted but does not respond, the UI still shows the attempt. If Claude rescues the run, its token spend is shown. Tavily appears as a search tool with pricing not tracked.
5. **Result** — Expand the vendor card to show claims, verdicts, confidence, receipts, and due-diligence questions.
6. **Close** — Receipts turns vendor marketing into a burden-of-proof workflow: claims in, public receipts out.

Suggested live input:

```text
Intercom Fin, https://www.intercom.com/fin
```

Suggested comparison input:

```text
Monday, https://monday.com
Asana, https://asana.com
ClickUp, https://clickup.com
```

## Telemetry interpretation

Example:

```text
Claude Sonnet 4.6 model · 8 attempts · $0.0399
Qwen 3 model · 10 attempts · 10 no response · $0.0020
Tavily search tool · 8 attempts · pricing not tracked
```

This means:

- Qwen was attempted first as the cheap tier.
- Qwen returned no usable completions for those attempts.
- Claude completed the successful model work and produced billable token usage.
- Tavily searched the public web for evidence.
- Tavily usage is counted as a tool attempt, but its external subscription/API cost is not included in LLM spend.

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
