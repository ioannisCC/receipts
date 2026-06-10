"""Stage A · EXTRACT. Cheap-tier LLM (Akamai/Qwen3-8B-FP8) decomposes a vendor
page's markdown into atomic outcome claims (FActScore / SAFE lineage).

Output is a list[Claim] with Pydantic-enforced shape: each claim has a metric,
magnitude, claim_type, and verbatim_span back into the source markdown."""

from __future__ import annotations

from app.schemas import Claim
from app.telemetry import TelemetryBus


async def extract(
    markdown: str,
    *,
    bus: TelemetryBus,
    vendor: str | None = None,
) -> list[Claim]:
    """Return atomic claims found in `markdown`. Empty list on hard failure —
    the orchestrator marks the vendor 'no_claims_extracted' and grey-cards it."""
    raise NotImplementedError("EXTRACT stage logic — next dispatch")
