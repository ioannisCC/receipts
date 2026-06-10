"""Stage D · ADVISE. Cheap-tier LLM. Given the vendor's judged claims, produce:
    - 3-5 questions a buyer should ask
    - 1 recommended next step

Output is plain text bound to the VendorResult.advice field."""

from __future__ import annotations

from app.schemas import Judgment
from app.telemetry import TelemetryBus


async def advise(
    vendor: str,
    judgments: list[Judgment],
    *,
    bus: TelemetryBus,
) -> str:
    """Return buyer-facing advice text. Empty string is acceptable on failure."""
    raise NotImplementedError("ADVISE stage logic — next dispatch")
