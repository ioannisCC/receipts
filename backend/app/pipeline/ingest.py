"""Stage INGEST. URL -> markdown text. Primary: httpx + trafilatura. Fallback:
Jina Reader (r.jina.ai/ prefix) for JS-heavy pages. Hard fail -> grey card
'unreachable — skipped'. Failure is a STATE, never a propagated exception.

NEVER use Browser Use here (CLAUDE.md). NEVER fetch G2/Capterra directly (they
block) — that's Stage B's snippet-only constraint, mentioned here as cross-ref."""

from __future__ import annotations

from app.telemetry import TelemetryBus


async def ingest(url: str, *, bus: TelemetryBus, vendor: str | None = None) -> str:
    """Fetch `url`, return clean markdown text. On any failure return an empty
    string and leave the per-vendor status='unreachable' decision to the
    orchestrator (this stage's contract is text-or-empty, not text-or-raise)."""
    raise NotImplementedError("INGEST stage logic — next dispatch")
