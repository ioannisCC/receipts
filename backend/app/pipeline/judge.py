"""Stage C · JUDGE. THE ROUTING STORY.

FrugalGPT cascade + AutoMix-style self-verification:
    1. Cheap tier (Qwen3-8B-FP8) issues verdict + confidence.
    2. If confidence < JUDGE_CONFIDENCE_THRESHOLD, escalate to premium (Sonnet).
    3. Premium verdict wins; `escalated=True` is recorded in the Judgment.

Target escalation rate: ~10-15%, displayed live on the demo.
NAIVE MODE = same code path with cascade disabled, everything Sonnet."""

from __future__ import annotations

from app.schemas import Claim, Evidence, Judgment
from app.telemetry import TelemetryBus


async def judge(
    claim: Claim,
    evidence: Evidence,
    *,
    bus: TelemetryBus,
    naive: bool = False,
    vendor: str | None = None,
) -> Judgment:
    """Cascade-judge the claim against found evidence. When `naive=True`, skip
    the cheap tier entirely and route straight to premium (this is the race
    counterfactual — same pipeline, cascade off)."""
    raise NotImplementedError("JUDGE stage logic — next dispatch")
