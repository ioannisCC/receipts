"""Stage B · HUNT. Per claim, run 2 Tavily queries:
    "{vendor} case study {metric}"
    "{vendor} reviews results"
and collect snippets + URLs. This stage is TOOLS, not an LLM. Receipts are
FOUND, never inferred.

Never fetch G2 / Capterra directly — they block. Use Tavily snippets only."""

from __future__ import annotations

from app.schemas import Claim, Evidence
from app.telemetry import TelemetryBus


async def hunt(
    vendor: str,
    claim: Claim,
    *,
    bus: TelemetryBus,
) -> Evidence:
    """Search the web for substantiation of `claim`. Always returns an Evidence —
    empty snippets/urls is a valid signal (Stage C will turn it into
    SELF_REPORTED_ONLY)."""
    raise NotImplementedError("HUNT stage logic — next dispatch")
