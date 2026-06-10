"""Stage C · JUDGE. THE ROUTING STORY.

FrugalGPT cascade + AutoMix-style self-verification:
    1. Cheap tier issues {verdict, confidence, rationale, receipts} as JSON.
    2. If confidence < JUDGE_CONFIDENCE_THRESHOLD OR JSON parse fails:
       escalate to premium (Sonnet). The premium-tier telemetry event carries
       escalated=True — this is where the demo's live escalation rate comes from.
    3. Empty/insufficient evidence still gets routed through cheap-tier, but the
       prompt instructs it to default to SELF_REPORTED_ONLY. Never penalize a
       vendor for a search miss.

NAIVE MODE = same code path with cascade off — every call goes straight to premium."""

from __future__ import annotations

from typing import Any

from app.clients import call_and_parse_json
from app.config import settings
from app.schemas import Claim, Evidence, Judgment, Verdict
from app.telemetry import TelemetryBus


JUDGE_SYSTEM = """You are a careful market-claim auditor.

You receive ONE marketing claim from a vendor plus EVIDENCE collected from public \
web search (snippets + URLs). You measure PUBLIC SUBSTANTIATION, never truth. \
Never label a claim "false."

Pick exactly one verdict:
- SUPPORTED: independent public receipts (case studies, third-party reviews, \
  published methodology) corroborate the claim. Snippets contain specific \
  numbers, customers, or methodology that align with the claim.
- SELF_REPORTED_ONLY: the only sources echoing the claim are vendor-owned \
  surfaces (their own site, blog, press releases, partner pages). DEFAULT TO \
  THIS when evidence is empty, thin, or only vendor-controlled.
- NO_PUBLIC_RECEIPT_FOUND: evidence was searched and is conspicuously absent or \
  directly contradicts the claim. Only use this when you have a positive reason \
  to believe receipts should exist but do not.

Return STRICT JSON:
{
  "verdict": "SUPPORTED" | "SELF_REPORTED_ONLY" | "NO_PUBLIC_RECEIPT_FOUND",
  "confidence": float in [0.0, 1.0],
  "rationale": "one concrete sentence",
  "receipts": ["url1", "url2"]
}

Output JSON only. No prose, no markdown fence."""

# TODO(akamai-swap): prepend "/no_think\n" to the user prompt below for Qwen3-8B.

_USER_TEMPLATE = """Vendor: {vendor}
Claim: {claim_text}
Metric: {metric}
Magnitude: {magnitude}

Evidence snippets:
{snippets}

Evidence URLs:
{urls}

Return the JSON judgment."""


def _build_user(vendor: str, claim: Claim, evidence: Evidence) -> str:
    snippets_str = "\n---\n".join(evidence.snippets) if evidence.snippets else "(none)"
    urls_str = "\n".join(evidence.urls) if evidence.urls else "(none)"
    return _USER_TEMPLATE.format(
        vendor=vendor or "Unknown",
        claim_text=claim.claim,
        metric=claim.metric or "(none)",
        magnitude=claim.magnitude or "(none)",
        snippets=snippets_str[:6000],
        urls=urls_str[:2000],
    )


def _parsed_to_judgment(
    parsed: Any, claim_id: str, *, escalated: bool, evidence_urls: list[str]
) -> Judgment | None:
    if not isinstance(parsed, dict):
        return None
    raw_verdict = str(parsed.get("verdict", "")).strip().upper()
    try:
        verdict = Verdict(raw_verdict)
    except ValueError:
        return None
    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    rationale = str(parsed.get("rationale", "")).strip()
    receipts_raw = parsed.get("receipts") or []
    receipts = [str(r) for r in receipts_raw if isinstance(r, (str, int))]
    # Only keep receipts that actually appeared in the evidence URLs, to prevent
    # the model from inventing citations.
    receipts = [r for r in receipts if r in evidence_urls]
    return Judgment(
        claim_id=claim_id,
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
        receipts=receipts,
        escalated=escalated,
    )


def _default_self_reported(claim_id: str, rationale: str, escalated: bool) -> Judgment:
    return Judgment(
        claim_id=claim_id,
        verdict=Verdict.SELF_REPORTED_ONLY,
        confidence=0.4,
        rationale=rationale,
        receipts=[],
        escalated=escalated,
    )


async def judge(
    claim: Claim,
    evidence: Evidence,
    *,
    bus: TelemetryBus,
    naive: bool = False,
    vendor: str | None = None,
) -> Judgment:
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": _build_user(vendor or "Unknown", claim, evidence)},
    ]

    if naive:
        _, parsed = await call_and_parse_json(
            bus,
            messages=messages,
            tier="premium",
            stage="judge",
            vendor=vendor,
            claim_id=claim.claim_id,
            max_tokens=512,
            escalated=False,
        )
        j = _parsed_to_judgment(parsed, claim.claim_id, escalated=False, evidence_urls=evidence.urls)
        return j or _default_self_reported(
            claim.claim_id, "naive-mode parse failure; defaulted", False
        )

    # Cascade: cheap first
    _, parsed = await call_and_parse_json(
        bus,
        messages=messages,
        tier="cheap",
        stage="judge",
        vendor=vendor,
        claim_id=claim.claim_id,
        max_tokens=512,
        escalated=False,
    )
    cheap_j = _parsed_to_judgment(parsed, claim.claim_id, escalated=False, evidence_urls=evidence.urls)

    escalate = cheap_j is None or cheap_j.confidence < settings.JUDGE_CONFIDENCE_THRESHOLD

    if not escalate and cheap_j is not None:
        return cheap_j

    # Escalate to premium
    _, parsed_prem = await call_and_parse_json(
        bus,
        messages=messages,
        tier="premium",
        stage="judge",
        vendor=vendor,
        claim_id=claim.claim_id,
        max_tokens=512,
        escalated=True,
    )
    prem_j = _parsed_to_judgment(parsed_prem, claim.claim_id, escalated=True, evidence_urls=evidence.urls)
    return prem_j or _default_self_reported(
        claim.claim_id, "cascade parse failure; defaulted", True
    )
