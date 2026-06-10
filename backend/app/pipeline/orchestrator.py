"""Per-vendor state machine + market-level batch runner.

One flow, five stages, run N× concurrent under a semaphore:
    URL -> [INGEST] -> [A: EXTRACT] -> [B: HUNT] -> [C: JUDGE] -> [D: ADVISE]
                                                          -> score -> leaderboard

`gather` is bound by its slowest task; per-stage timeouts (asyncio.wait_for) and
tenacity-style backoff keep the sweep moving — failure is a grey card, never a
raised exception that stalls the whole batch."""

from __future__ import annotations

from app.schemas import MarketResult, VendorResult
from app.telemetry import TelemetryBus


async def run_vendor(
    vendor: str,
    url: str,
    *,
    bus: TelemetryBus,
    naive: bool = False,
) -> VendorResult:
    """Run all five stages for one vendor. Always returns a VendorResult — never
    raises. Per-stage failures are reflected in `status` and grey-carded on UI."""
    raise NotImplementedError("orchestrator per-vendor flow — next dispatch")


async def run_market(
    category: str,
    vendor_urls: list[tuple[str, str]],
    *,
    bus: TelemetryBus,
    naive: bool = False,
    n: int | None = None,
    semaphore_size: int | None = None,
) -> MarketResult:
    """Run N vendors concurrently under a semaphore. `naive=True` flips the
    cascade off across every stage that uses it (the race counterfactual)."""
    raise NotImplementedError("orchestrator batch loop — next dispatch")
