"""Stage D · ADVISE. Cheap-tier (or premium in naive mode). Given the vendor's
judged claims, produce buyer-facing questions + one recommended next step.

Free-text output, assigned to VendorResult.advice."""

from __future__ import annotations

from typing import Literal

from app.clients import chat, cost_usd
from app.config import settings
from app.schemas import Judgment
from app.telemetry import TelemetryBus, measure


_USER_TEMPLATE = """Vendor: {vendor}

Audit findings (one line per claim):
{findings}

Write for a prospective buyer evaluating this vendor:
1. 3-5 concrete questions they should ask the vendor's sales team, each on its own line, prefixed with "- ".
2. One sentence starting with "Recommended next step:" suggesting the single most useful follow-up.

Output plain text. Be specific to the claims above. No markdown headings."""


async def advise(
    vendor: str,
    judgments: list[Judgment],
    *,
    bus: TelemetryBus,
    tier: Literal["cheap", "premium"] = "cheap",
) -> str:
    findings = "\n".join(
        f"- [{j.verdict.value}] {j.rationale}" for j in judgments if j.rationale
    ) or "- (no judged claims)"
    user = _USER_TEMPLATE.format(vendor=vendor, findings=findings)
    messages = [{"role": "user", "content": user}]
    model_name = settings.CHEAP_MODEL if tier == "cheap" else settings.PREMIUM_MODEL

    async with measure(bus, stage="advise", model=model_name, vendor=vendor) as m:
        result = await chat(tier, messages, max_tokens=600, temperature=0.2)
        m.tokens_in = result.tokens_in
        m.tokens_out = result.tokens_out
        m.cost_usd = cost_usd(model_name, result.tokens_in, result.tokens_out)
    return result.text.strip()
