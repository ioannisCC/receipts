#!/usr/bin/env bash
# Guided walkthrough of the Receipts codebase.
# Run: bash explain.sh

BOLD='\033[1m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
RESET='\033[0m'

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend/app"
FRONTEND="$ROOT/frontend/src"

divider() { echo -e "${DIM}────────────────────────────────────────────────────────────${RESET}"; }
header()   { echo; divider; echo -e "${BOLD}${CYAN}$1${RESET}"; divider; }
step()     { echo -e "\n${GREEN}▶ $1${RESET}"; }
note()     { echo -e "  ${YELLOW}→${RESET} $1"; }
show()     { echo -e "${DIM}"; grep -n "" "$1" | head -"${2:-30}" | sed 's/^/  /'; echo -e "${RESET}"; }

clear
echo -e "${BOLD}RECEIPTS — Burden of Proof${RESET}"
echo    "An AI-powered market claim auditor."
echo    "You give it a software category + vendor URLs."
echo    "It finds their marketing claims and checks if they have public proof."

# ─── OVERVIEW ───────────────────────────────────────────────────────────────

header "PIPELINE OVERVIEW"
echo "Every vendor runs through five stages in sequence:"
echo
echo "  URL  →  [INGEST]  →  [EXTRACT]  →  [HUNT]  →  [JUDGE]  →  [ADVISE]"
echo "                                                      ↓"
echo "                                               SCORE  →  LEADERBOARD"
echo
echo "All vendors run concurrently under a semaphore (default: 8 at once)."
note "orchestrator.py wires all stages together."

# ─── CONFIG ─────────────────────────────────────────────────────────────────

header "1. CONFIG  ($BACKEND/config.py)"
note "All tuning knobs live here, loaded from .env"
note "Two LLM tiers: cheap (Akamai/Qwen3-8B) and premium (Claude Sonnet)"
note "Key timeouts: SCRAPE=10s, LLM=45s, CHEAP_LLM=20s"
show "$BACKEND/config.py" 49

# ─── INGEST ─────────────────────────────────────────────────────────────────

header "2. STAGE A — INGEST  ($BACKEND/pipeline/ingest.py)"
note "Fetches the vendor homepage and converts it to clean markdown text."
note "Uses httpx + trafilatura. Falls back to Jina Reader for JS-heavy pages."
note "Caches results on disk — re-runs don't re-scrape."
note "Returns empty string on failure; orchestrator grey-cards the vendor."
show "$BACKEND/pipeline/ingest.py" 62

# ─── EXTRACT ────────────────────────────────────────────────────────────────

header "3. STAGE B — EXTRACT  ($BACKEND/pipeline/extract.py)"
note "Cheap LLM (Qwen3-8B via Akamai) reads the page and finds quantified claims."
note "Only keeps claims with a real number/percentage/ratio — ignores vague phrases."
note "Falls back to a fast regex extractor if the LLM is cold or times out."
note "Output: list[Claim] — each with metric, magnitude, claim_type, verbatim_span."
echo
echo "  Example input:  'Our AI resolves 65% of support tickets automatically'"
echo "  Example output:"
echo '  { "claim": "Resolves 65% of tickets", "metric": "resolution_rate",'
echo '    "magnitude": "65%", "claim_type": "performance" }'

# ─── HUNT ───────────────────────────────────────────────────────────────────

header "4. STAGE C — HUNT  ($BACKEND/pipeline/hunt.py)"
note "For each claim, runs 2 Tavily searches in parallel:"
note "  1. '{vendor} {metric} case study results'"
note "  2. '{vendor} customer review {magnitude} verified'"
note "Collects snippets + URLs. This is pure tool use — no LLM."
note "Results are cached on disk. Receipts are FOUND, never inferred."
show "$BACKEND/pipeline/hunt.py" 70

# ─── JUDGE ──────────────────────────────────────────────────────────────────

header "5. STAGE D — JUDGE  ($BACKEND/pipeline/judge.py)"
note "Verdicts each claim against the evidence found in Hunt."
note "Uses a FrugalGPT-style cascade:"
note "  1. Cheap model (Qwen3-8B) → verdict + confidence score"
note "  2. If confidence < 0.7, escalate to Claude Sonnet (premium)"
note "Target: ~10-15% escalation rate — cheap handles the easy calls."
echo
echo "  Three possible verdicts:"
echo "    SUPPORTED          — independent 3rd-party evidence confirms the claim"
echo "    SELF_REPORTED_ONLY — only vendor's own site mentions it"
echo "    NO_PUBLIC_RECEIPT_FOUND — searched, nothing found"
echo
note "Naive mode (race counterfactual): skips cheap tier, all-Sonnet."

# ─── ADVISE ─────────────────────────────────────────────────────────────────

header "6. STAGE E — ADVISE  ($BACKEND/pipeline/advise.py)"
step "Generates buyer-facing follow-up questions for each vendor."
echo "  Example: 'Can you share the Gartner report title, date, and link?'"
note "Cheap LLM. One call per vendor after all claims are judged."

# ─── SCORING ────────────────────────────────────────────────────────────────

header "7. SCORING  ($BACKEND/scoring.py)"
note "Rolls up judgments into a vendor credibility score:"
echo
echo "  SUPPORTED           = 1.0 pts"
echo "  SELF_REPORTED_ONLY  = 0.4 pts"
echo "  NO_PUBLIC_RECEIPT   = 0.0 pts"
echo "  Score = sum(weights) / n_claims"
echo
note "Claim Inflation Index = avg(claims_made / max(claims_supported, 1))"
note "  e.g. 10 claims, 2 supported → 5.0x inflation"
note "Also builds: claim clusters, market benchmark, best/worst vendor."

# ─── CLIENTS ────────────────────────────────────────────────────────────────

header "8. LLM CLIENTS  ($BACKEND/clients.py)"
note "Two-tier client. cheap=OpenAI-compat (Akamai vLLM), premium=Anthropic SDK."
note "chat(tier, messages) is the single call surface for all pipeline stages."
note "Cost is tracked per call from a hardcoded rate table."
note "Qwen3 thinking mode is disabled via /no_think injection."
note "Also hosts generate_image() for the Magnific honest-ad stage."

# ─── TELEMETRY ──────────────────────────────────────────────────────────────

header "9. TELEMETRY  ($BACKEND/telemetry.py)"
note "Every external call is wrapped in measure(bus, stage=...) context manager."
note "Emits TelemetryEvent: stage, model, tokens_in/out, latency, cost, escalated."
note "Events stream live to the frontend over Server-Sent Events (SSE)."
note "Also written to backend/app/logs/run_<id>.jsonl for replay."

# ─── API ────────────────────────────────────────────────────────────────────

header "10. API  ($BACKEND/server.py)"
echo
echo "  POST /audit                    — start a run, returns run_id"
echo "  GET  /audit/{run_id}/stream    — SSE telemetry stream"
echo "  GET  /audit/{run_id}/results   — partial or final results"
echo "  GET  /healthz                  — liveness check"
echo
note "Each run gets an in-memory TelemetryBus. Results are partial-updated live."

# ─── FRONTEND ───────────────────────────────────────────────────────────────

header "11. FRONTEND  ($FRONTEND/App.tsx)"
note "React + Vite. Opens SSE connection after POST /audit."
note "Renders live telemetry cards, vendor scorecards, claim detail rows."
note "Preset categories (AI SDRs, AI Support Agents) or custom vendor paste."
note "Vite proxies /audit and /healthz to localhost:8000."

# ─── DATA ───────────────────────────────────────────────────────────────────

header "12. VENDOR DATA  ($ROOT/backend/data/vendors/)"
note "JSON files with preset vendor lists per category."
ls "$ROOT/backend/data/vendors/" 2>/dev/null | sed 's/^/    /'

# ─── WRAP UP ────────────────────────────────────────────────────────────────

header "DONE"
echo "Key files at a glance:"
echo
echo "  config.py          — all env/tuning knobs"
echo "  pipeline/ingest.py — scrape → markdown"
echo "  pipeline/extract.py— markdown → claims (cheap LLM)"
echo "  pipeline/hunt.py   — claims → evidence (Tavily x2, parallel)"
echo "  pipeline/judge.py  — evidence → verdicts (cascade cheap→premium)"
echo "  pipeline/advise.py — verdicts → buyer questions (cheap LLM)"
echo "  scoring.py         — credibility score + Claim Inflation Index"
echo "  clients.py         — two-tier LLM + Magnific image gen"
echo "  telemetry.py       — measure() wrapper + SSE bus"
echo "  server.py          — FastAPI endpoints"
echo "  frontend/App.tsx   — React UI"
echo
divider
