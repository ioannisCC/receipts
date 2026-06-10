# Receipts Project Guide

Receipts is an AI-powered market claim auditor.

In simple terms: you give it a software category and a list of vendor websites. It reads each vendor's homepage, pulls out marketing claims, searches the public web for evidence, judges whether the claims are publicly supported, and shows a credibility leaderboard.

The project is designed to answer questions like:

- Which vendors make the most believable claims?
- Which claims are backed by independent public evidence?
- Which claims only appear on the vendor's own website?
- Which claims have no public receipt at all?
- What should a buyer ask before trusting the vendor?

## Main Idea

Most SaaS vendor pages make bold claims:

- "Trusted by 60% of the Fortune 500"
- "Cuts support costs by 50%"
- "Recognized as a leader by Gartner"
- "Automates 80% of tickets"

Receipts checks whether those claims have public proof.

It does not claim to measure absolute truth. It measures public substantiation. A claim may be true privately, but if there is no public evidence, Receipts will mark it as weakly supported.

## What The App Produces

For each vendor, Receipts returns:

- Extracted claims from the vendor website
- Evidence snippets and source URLs found on the web
- A judgment for each claim
- A confidence score for each judgment
- A rationale explaining the verdict
- A vendor credibility score
- Buyer questions to ask the vendor
- A next recommended step

For a whole category, Receipts returns:

- A market leaderboard
- A Claim Inflation Index
- Average market credibility
- Best and worst scoring vendors
- Total claims checked
- Total supported claims
- Common claim clusters across vendors
- Live telemetry including cost, tokens, latency, and escalations

## Verdicts

Each claim gets one of three verdicts.

| Verdict | Meaning |
| --- | --- |
| `SUPPORTED` | Independent public evidence corroborates the claim. |
| `SELF_REPORTED_ONLY` | The claim appears on vendor-owned pages, but no independent confirmation was found. |
| `NO_PUBLIC_RECEIPT_FOUND` | The system searched and did not find public evidence for the claim. |

## Credibility Score

Each vendor gets a credibility score based on its judged claims.

The scoring weights are:

| Verdict | Weight |
| --- | --- |
| `SUPPORTED` | `1.0` |
| `SELF_REPORTED_ONLY` | `0.4` |
| `NO_PUBLIC_RECEIPT_FOUND` | `0.0` |

Example:

If a vendor has two claims:

- 1 self-reported claim
- 1 no-receipt claim

The score is:

```text
(0.4 + 0.0) / 2 = 0.2
```

So the UI shows:

```text
20%
```

## Claim Inflation Index

The Claim Inflation Index measures how much marketing claim volume exists compared with substantiated claims.

The basic idea is:

```text
claims made / claims supported
```

If a category has many claims but few public receipts, the index goes up.

Example:

```text
10 claims, 2 supported = 5.0x
```

That means the category makes about 5 claims for every claim that has public support.

## Architecture

The pipeline works like this:

```text
URL -> INGEST -> EXTRACT -> HUNT -> JUDGE -> ADVISE -> SCORE -> LEADERBOARD
```

### 1. Ingest

The backend fetches the vendor website and turns the page into readable text.

Tools used:

- `httpx`
- `trafilatura`
- Jina Reader fallback for difficult JavaScript-heavy pages

### 2. Extract

An LLM extracts atomic claims from the website text.

Example input:

```text
Our AI agent resolves 65% of support tickets automatically.
```

Example extracted claim:

```json
{
  "claim": "AI agent resolves 65% of support tickets automatically",
  "metric": "resolution rate",
  "magnitude": "65%",
  "claim_type": "performance"
}
```

### 3. Hunt

The system searches for public evidence for each claim.

Tools used:

- Tavily search
- Vendor and non-vendor public web pages

### 4. Judge

The system judges whether the evidence supports the claim.

The project uses a cost-aware inference cascade:

- Cheap model first for most judgments
- Frontier model only when confidence is low or escalation is needed

This is meant to reduce cost while preserving judgment quality.

### 5. Advise

The system writes buyer-facing follow-up questions.

Example:

```text
Can you provide the direct Gartner report title, date, and link?
```

### 6. Score

The system calculates:

- Vendor credibility score
- Market Claim Inflation Index
- Claim clusters
- Benchmarks

## Backend

The backend is a Python FastAPI app.

Important files:

```text
backend/app/server.py
backend/app/pipeline/orchestrator.py
backend/app/pipeline/ingest.py
backend/app/pipeline/extract.py
backend/app/pipeline/hunt.py
backend/app/pipeline/judge.py
backend/app/pipeline/advise.py
backend/app/scoring.py
backend/app/schemas.py
backend/app/telemetry.py
backend/app/config.py
```

Main backend endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Check if the API is running. |
| `POST /audit` | Start a new audit run. |
| `GET /audit/{run_id}/stream` | Stream live telemetry events. |
| `GET /audit/{run_id}/results` | Fetch partial or final audit results. |

## Frontend

The frontend is a React + Vite app.

Important files:

```text
frontend/src/App.tsx
frontend/src/index.css
frontend/src/main.tsx
frontend/package.json
frontend/vite.config.ts
```

The UI lets you:

- Pick a preset category
- Enter your own category
- Paste your own vendor list
- Start an audit
- Watch telemetry update live
- See vendor score cards
- Expand each vendor's claims
- Read verdict rationales
- Read buyer advice
- Compare vendors in a category

## Current Presets

The frontend includes presets for:

- AI Support Agents
- AI SDRs

Example AI Support Agents vendors:

```text
Intercom Fin, https://www.intercom.com/fin
Decagon, https://decagon.ai
Zendesk AI, https://www.zendesk.com/service/ai
Forethought, https://forethought.ai
Tidio, https://www.tidio.com
Freshdesk AI, https://www.freshworks.com/freshdesk
```

Example AI SDR vendors:

```text
11x, https://www.11x.ai
Artisan, https://www.artisan.co
Qualified, https://www.qualified.com
AiSDR, https://aisdr.com
Regie.ai, https://www.regie.ai
Outreach, https://www.outreach.io
```

## Enter Your Own Vendors

Use this format in the frontend:

```text
Name, https://website.com
Name, https://website.com
Name, https://website.com
```

Example:

```text
Monday, https://monday.com
Asana, https://asana.com
ClickUp, https://clickup.com
Airtable, https://www.airtable.com
Smartsheet, https://www.smartsheet.com
```

Category:

```text
Project Management Software
```

You can also use tabs instead of commas:

```text
Monday	https://monday.com
Asana	https://asana.com
ClickUp	https://clickup.com
```

The URL must start with `http` or `https`.

## More Example Categories

### Productivity Software

```text
Notion, https://www.notion.com
Coda, https://coda.io
Airtable, https://www.airtable.com
ClickUp, https://clickup.com
```

### Project Management Software

```text
Linear, https://linear.app
Jira, https://www.atlassian.com/software/jira
Asana, https://asana.com
Monday, https://monday.com
```

### HR And Recruiting AI

```text
Paradox, https://www.paradox.ai
Eightfold, https://eightfold.ai
Ashby, https://www.ashbyhq.com
Greenhouse, https://www.greenhouse.com
```

### Accounting And Spend Automation

```text
Ramp, https://ramp.com
Brex, https://www.brex.com
Airbase, https://www.airbase.com
Navan, https://navan.com
```

## Setup

Requirements:

- Python 3.12
- `uv`
- Node.js
- npm

Install backend dependencies:

```bash
cd backend
uv sync
source .venv/bin/activate
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

## Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Then fill in:

```text
AKAMAI_INFERENCE_URL=
AKAMAI_TOKEN=
ANTHROPIC_API_KEY=
TAVILY_API_KEY=
TAVILY_API_KEY_BACKUP=
```

Optional run knobs:

```text
N_VENDORS=10
SEMAPHORE=8
JUDGE_CONFIDENCE_THRESHOLD=0.7
SCRAPE_TIMEOUT_S=10
LLM_TIMEOUT_S=45
```

## Running The Backend

From the project root:

```bash
cd backend
source .venv/bin/activate
uvicorn app.server:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/healthz
```

Expected response:

```json
{"status":"ok"}
```

## Running The Frontend

From the project root:

```bash
cd frontend
npm run dev
```

Open the URL Vite prints. It is usually:

```text
http://localhost:5173
```

## Starting An Audit With Curl

Start a small one-vendor audit:

```bash
curl -X POST http://127.0.0.1:8000/audit \
  -H "Content-Type: application/json" \
  -d '{
    "category": "Project Management Software",
    "vendor_urls": [
      ["Monday", "https://monday.com"]
    ],
    "n": 1
  }'
```

The response includes:

```json
{
  "run_id": "...",
  "stream_url": "/audit/.../stream",
  "results_url": "/audit/.../results"
}
```

Fetch results:

```bash
curl http://127.0.0.1:8000/audit/YOUR_RUN_ID/results
```

Watch live telemetry:

```bash
curl http://127.0.0.1:8000/audit/YOUR_RUN_ID/stream
```

## Testing

Backend syntax check:

```bash
cd backend
./.venv/bin/python -m py_compile app/server.py app/pipeline/orchestrator.py app/scoring.py app/schemas.py app/config.py
```

Frontend build:

```bash
cd frontend
npm run build
```

Akamai cheap-tier smoke test:

```bash
cd backend
python scripts/smoke_akamai.py
```

Evidence smoke test:

```bash
cd backend
python scripts/test_evidence.py
```

Standalone hunt test:

```bash
cd backend
python scripts/verify_hunt.py
```

## Telemetry

Every external call is measured and emitted as a telemetry event.

Telemetry includes:

- Stage
- Model
- Input tokens
- Output tokens
- Latency
- Time to first token
- Cost
- Whether the call escalated
- Vendor
- Claim ID

Live telemetry streams to the frontend through Server-Sent Events.

Telemetry is also written to local JSONL logs:

```text
backend/app/logs/run_<run_id>.jsonl
```

## Feature List

Core features:

- Vendor homepage scraping
- Claim extraction
- Public evidence search
- Claim-by-claim verdicts
- Verdict confidence scores
- Judgment rationales
- Evidence URL collection
- Buyer advice generation
- Vendor credibility scoring
- Market leaderboard
- Claim Inflation Index
- Category-level benchmarks
- Claim clustering across vendors
- Live SSE telemetry
- JSONL replay logs
- Cost tracking
- Token tracking
- Latency tracking
- Escalation tracking
- Configurable concurrency
- Configurable vendor count
- Preset vendor categories
- Custom vendor input

Developer features:

- FastAPI backend
- React + Vite frontend
- Pydantic schemas for all pipeline outputs
- Async pipeline orchestration
- Per-stage timeouts
- Semaphore-based concurrency
- Disk cache support
- Environment-based configuration
- Smoke scripts for external services

## Known Practical Notes

- Full audits require working LLM and Tavily credentials.
- Some vendor sites are JavaScript-heavy and may scrape poorly.
- The app measures public evidence, not private truth.
- Low scores do not prove a claim is false. They mean the public evidence trail was weak.
- Results can vary when vendor pages or public search results change.
- Smaller vendor sets are faster and easier to inspect manually.

## Demo Readiness Plan

This project is already a mostly built product, not just a proposal. The main work before a demo is to get the real credentials wired in, run the smoke tests, run at least one audit end to end, and polish the live story.

### Already Built

- Full pipeline: ingest -> extract -> hunt -> judge -> advise -> score -> leaderboard
- FastAPI backend with audit endpoints
- React + Vite frontend
- Live SSE telemetry streaming
- Pydantic schemas for every stage
- Credibility scoring
- Claim Inflation Index
- Preset vendor categories
- Custom vendor input
- JSONL replay logs
- Smoke test scripts
- Environment-based config

### Do First Tonight

1. Set up the environment:

```bash
cp .env.example .env
```

Fill in:

```text
AKAMAI_INFERENCE_URL=
AKAMAI_TOKEN=
ANTHROPIC_API_KEY=
TAVILY_API_KEY=
TAVILY_API_KEY_BACKUP=
```

2. Start the backend:

```bash
cd backend
uv sync
source .venv/bin/activate
uvicorn app.server:app --reload
```

3. Start the frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

4. Run the smoke tests:

```bash
cd backend
python scripts/smoke_akamai.py
python scripts/test_evidence.py
python scripts/verify_hunt.py
```

5. Run one small audit end to end:

```bash
curl -X POST http://127.0.0.1:8000/audit \
  -H "Content-Type: application/json" \
  -d '{
    "category": "Project Management Software",
    "vendor_urls": [["Monday", "https://monday.com"]],
    "n": 1
  }'
```

If this returns real claims, verdicts, rationales, and advice, the core demo path is working.

### Demo Polish Still Missing

These are polish tasks, not core pipeline tasks:

- Race mode: naive frontier-only run vs routed cascade run, side by side
- Cost tickers for naive vs routed mode
- Audience vote or category picker screen
- Closing stats card generated from live telemetry
- Akamai sponsor audit using Akamai's own public claims
- Final curated vendor lists for the demo categories

### Suggested Team Split

If four people are working on it:

- Person 1: own credentials, Akamai endpoint setup, full audit run, and backend reliability
- Person 2: build race mode UI with naive vs routed cost comparison
- Person 3: build audience vote/category picker and closing stats card
- Person 4: curate vendor lists, pre-run sponsor audit, and own the pitch script

### Demo Priority

The most important goal is not to add more pipeline functionality. It is to prove the existing loop works:

```text
vendor URL -> claims -> evidence -> verdicts -> score -> buyer advice
```

Once that works for one vendor, scale to a small category. Once that works, polish the story.

## Good First Demo

Use this category:

```text
Project Management Software
```

Use these vendors:

```text
Monday, https://monday.com
Asana, https://asana.com
ClickUp, https://clickup.com
Airtable, https://www.airtable.com
Smartsheet, https://www.smartsheet.com
```

Start with `n = 1` or `n = 2` if you want a faster test.

Then expand each vendor card and inspect:

- Claims
- Verdicts
- Confidence
- Rationale
- Buyer advice

## How To Interpret Results

If a vendor gets `SUPPORTED`, the app found independent public evidence.

If a vendor gets `SELF_REPORTED_ONLY`, the claim may be real, but the public evidence found came from the vendor itself.

If a vendor gets `NO_PUBLIC_RECEIPT_FOUND`, the app searched and did not find public proof for that specific claim.

The most useful part is often the advice section. It tells a buyer exactly what to ask the vendor next.
