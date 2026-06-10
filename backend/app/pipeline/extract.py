"""Stage A · EXTRACT. Cheap-tier LLM decomposes vendor markdown into atomic
outcome claims (FActScore / SAFE lineage). Strict JSON out -> pydantic-validated.

A parse failure after one retry yields []; the orchestrator grey-cards the
vendor as 'no_claims_extracted'."""

from __future__ import annotations

from typing import Literal

from app.clients import call_and_parse_json
from app.schemas import Claim
from app.telemetry import TelemetryBus


EXTRACT_SYSTEM = """You are a market-claim analyst.

Given a vendor's marketing page in markdown, extract every ATOMIC OUTCOME CLAIM \
-- a single quantifiable result the vendor attributes to using their product. \
Skip generic capability statements ("AI-powered", "modern stack"); focus on \
claims with a metric, magnitude, or named customer outcome.

Return STRICT JSON: a top-level array. Each element:
{
  "claim": "short paraphrase, one sentence",
  "metric": "the metric named (string), or null",
  "magnitude": "the number / quantifier (e.g. '40%', '3x', '$2M'), or null",
  "claim_type": "one of: performance, cost, time, quality, scale, accuracy, other",
  "verbatim_span": "exact substring from the markdown that supports the claim"
}

If there are NO atomic outcome claims, return [].
Output JSON only. No prose, no markdown fence."""

# TODO(akamai-swap): prepend "/no_think\n" to the user prompt below for Qwen3-8B.
# Qwen3-8B emits <think> traces that break json.loads; harmless on Haiku, mandatory on Qwen3.

_USER_TEMPLATE = """Vendor: {vendor}

Markdown:
\"\"\"
{md}
\"\"\"

Return the JSON array."""


def _slug(vendor: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in vendor.lower()).strip("-") or "v"


async def extract(
    markdown: str,
    *,
    bus: TelemetryBus,
    vendor: str | None = None,
    tier: Literal["cheap", "premium"] = "cheap",
) -> list[Claim]:
    if not markdown.strip():
        return []

    user = _USER_TEMPLATE.format(vendor=vendor or "Unknown", md=markdown[:14000])
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": user},
    ]
    _, parsed = await call_and_parse_json(
        bus,
        messages=messages,
        tier=tier,
        stage="extract",
        vendor=vendor,
        max_tokens=2048,
    )

    if not isinstance(parsed, list):
        return []

    claims: list[Claim] = []
    slug = _slug(vendor or "v")
    for i, raw in enumerate(parsed):
        if not isinstance(raw, dict):
            continue
        try:
            c = Claim(
                claim_id=f"{slug}-{i:03d}",
                claim=str(raw.get("claim", "")).strip(),
                metric=(str(raw["metric"]) if raw.get("metric") else None),
                magnitude=(str(raw["magnitude"]) if raw.get("magnitude") else None),
                claim_type=str(raw.get("claim_type", "other")).strip() or "other",
                verbatim_span=str(raw.get("verbatim_span", "")).strip(),
            )
            if c.claim:
                claims.append(c)
        except Exception:
            continue
    return claims
