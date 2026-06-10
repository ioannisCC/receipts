"""Verify hunt() standalone with a hardcoded hand-written Claim. No LLM, just Tavily.

Hardcoded inputs (transparent — not agent-inferred):
    vendor = "Intercom Fin"
    claim.metric = "resolution rate"
    claim.claim  = "Fin resolves 65% of customer queries automatically"

Expected: ≥1 snippet and ≥1 url returned. Hunt should not raise.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.hunt import hunt  # noqa: E402
from app.schemas import Claim  # noqa: E402
from app.telemetry import TelemetryBus  # noqa: E402


CLAIM = Claim(
    claim_id="manual-001",
    claim="Fin resolves 65% of customer queries automatically",
    metric="resolution rate",
    magnitude="65%",
    claim_type="performance",
    verbatim_span="Fin resolves 65% of customer queries automatically",
)


async def main() -> int:
    bus = TelemetryBus()
    ev = await hunt("Intercom Fin", CLAIM, bus=bus)
    print(f"snippets: {len(ev.snippets)}  urls: {len(ev.urls)}")
    for u in ev.urls[:5]:
        print(f"  - {u}")
    print("--- first snippet ---")
    print((ev.snippets[0] if ev.snippets else "(none)")[:400])
    return 0 if (ev.snippets and ev.urls) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
