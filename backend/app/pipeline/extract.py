"""Stage A · EXTRACT. Cheap-tier LLM (Akamai/Qwen3-8B-FP8) decomposes a vendor
page's markdown into atomic outcome claims (FActScore / SAFE lineage).

Output is a list[Claim] with Pydantic-enforced shape: each claim has a metric,
magnitude, claim_type, and verbatim_span back into the source markdown."""

from __future__ import annotations

import hashlib
import json
import re

from app.clients import chat, cost_usd
from app.schemas import Claim
from app.telemetry import TelemetryBus, measure

_SYSTEM = """You are a precise claim extractor for an AI market auditor.

Extract every specific, quantified outcome claim from the vendor marketing text below.
Only include claims with a concrete number, percentage, ratio, or measurable outcome.
Skip vague marketing phrases like "industry-leading", "best-in-class", or "enterprise-grade".

Return ONLY a valid JSON array. No markdown, no explanation, just the JSON.
Each element must have exactly these keys:
- "claim": full claim statement (1 sentence)
- "metric": what is being measured (e.g. "resolution_rate", "cost_reduction", "csat_score")
- "magnitude": the specific number/ratio (e.g. "45%", "3x", "90%", "$2M")
- "claim_type": one of "performance", "cost", "accuracy", "speed", "scale", "reliability"
- "verbatim_span": the exact phrase from the source text (keep it short, ≤15 words)

Example output:
[
  {"claim": "Resolves 45% of support tickets automatically", "metric": "resolution_rate", "magnitude": "45%", "claim_type": "performance", "verbatim_span": "resolves 45% of support tickets automatically"},
  {"claim": "3x faster response time", "metric": "response_time", "magnitude": "3x", "claim_type": "speed", "verbatim_span": "3x faster response time"}
]

If no quantified claims are found, return [].
"""


def _strip_json(text: str) -> str:
    """Strip markdown code fences if the model wraps its JSON output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*$", "", text)
    return text.strip()


def _claim_id(vendor: str | None, span: str, index: int) -> str:
    key = f"{vendor or ''}:{span}:{index}"
    return hashlib.sha1(key.encode()).hexdigest()[:10]


async def extract(
    markdown: str,
    *,
    bus: TelemetryBus,
    vendor: str | None = None,
) -> list[Claim]:
    """Return atomic claims found in `markdown`. Empty list on hard failure —
    the orchestrator marks the vendor 'no_claims_extracted' and grey-cards it."""
    if not markdown.strip():
        return []

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Vendor page text:\n\n{markdown[:12_000]}"},
    ]

    async with measure(bus, stage="extract", vendor=vendor) as m:
        try:
            result = await chat("cheap", messages, max_tokens=1024, temperature=0.0)
            m.tokens_in = result.tokens_in
            m.tokens_out = result.tokens_out
            m.model = result.model
            m.cost_usd = cost_usd(result.model, result.tokens_in, result.tokens_out)

            raw = _strip_json(result.text)
            data = json.loads(raw)
            if not isinstance(data, list):
                return []

            claims: list[Claim] = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                try:
                    claims.append(
                        Claim(
                            claim_id=_claim_id(vendor, item.get("verbatim_span", ""), i),
                            claim=str(item.get("claim", "")),
                            metric=item.get("metric"),
                            magnitude=item.get("magnitude"),
                            claim_type=str(item.get("claim_type", "performance")),
                            verbatim_span=str(item.get("verbatim_span", "")),
                        )
                    )
                except Exception:
                    continue
            return claims
        except Exception:
            return []
