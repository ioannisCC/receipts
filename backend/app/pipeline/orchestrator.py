"""Per-vendor state machine + market-level batch runner.

One flow, five stages, run N× concurrent under a semaphore:
    URL -> [INGEST] -> [A: EXTRACT] -> [B: HUNT] -> [C: JUDGE] -> [D: ADVISE]
                                                          -> score -> leaderboard

`gather` is bound by its slowest task; per-stage timeouts (asyncio.wait_for) and
tenacity-style backoff keep the sweep moving — failure is a grey card, never a
raised exception that stalls the whole batch."""

from __future__ import annotations

import asyncio

from app.config import settings
from app.pipeline.advise import advise
from app.pipeline.extract import extract
from app.pipeline.hunt import hunt
from app.pipeline.ingest import ingest
from app.pipeline.judge import judge
from app.schemas import Judgment, MarketResult, VendorResult
from app.scoring import finalize_market, vendor_credibility
from app.telemetry import TelemetryBus, TelemetryEvent


async def run_vendor(
    vendor: str,
    url: str,
    *,
    bus: TelemetryBus,
    naive: bool = False,
) -> VendorResult:
    """Run all five stages for one vendor. Always returns a VendorResult — never
    raises. Per-stage failures are reflected in `status` and grey-carded on UI."""

    # INGEST
    try:
        markdown = await asyncio.wait_for(
            ingest(url, bus=bus, vendor=vendor),
            timeout=settings.SCRAPE_TIMEOUT_S * 2,
        )
    except asyncio.TimeoutError:
        markdown = ""

    if not markdown.strip():
        result = VendorResult(vendor=vendor, url=url, status="unreachable")
        bus.emit(TelemetryEvent(stage="vendor_done", vendor=vendor))
        return result

    # EXTRACT
    try:
        claims = await asyncio.wait_for(
            extract(markdown, bus=bus, vendor=vendor),
            timeout=settings.LLM_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        claims = []

    if not claims:
        result = VendorResult(vendor=vendor, url=url, status="no_claims_extracted")
        bus.emit(TelemetryEvent(stage="vendor_done", vendor=vendor))
        return result

    # HUNT + JUDGE per claim (all concurrent)
    async def _hunt_and_judge(claim) -> Judgment | None:
        try:
            evidence = await asyncio.wait_for(
                hunt(vendor, claim, bus=bus),
                timeout=settings.SCRAPE_TIMEOUT_S * 2,
            )
        except asyncio.TimeoutError:
            from app.schemas import Evidence
            evidence = Evidence(claim_id=claim.claim_id)
        try:
            return await asyncio.wait_for(
                judge(claim, evidence, bus=bus, naive=naive, vendor=vendor),
                timeout=settings.LLM_TIMEOUT_S * 2,
            )
        except asyncio.TimeoutError:
            return None

    raw_judgments = await asyncio.gather(
        *[_hunt_and_judge(c) for c in claims], return_exceptions=True
    )
    judgments = [j for j in raw_judgments if isinstance(j, Judgment)]

    # ADVISE
    try:
        advice_text = await asyncio.wait_for(
            advise(vendor, judgments, bus=bus),
            timeout=settings.LLM_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        advice_text = ""

    result = VendorResult(
        vendor=vendor,
        url=url,
        status="ok",
        claims=claims,
        judgments=judgments,
        credibility_score=vendor_credibility(judgments),
        advice=advice_text,
    )
    bus.emit(TelemetryEvent(stage="vendor_done", vendor=vendor))
    return result


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
    cap = n or settings.N_VENDORS
    sem_size = semaphore_size or settings.SEMAPHORE
    pairs = list(vendor_urls)[:cap]

    sem = asyncio.Semaphore(sem_size)
    market = MarketResult(category=category)

    async def _bounded(vendor: str, url: str) -> VendorResult:
        async with sem:
            return await run_vendor(vendor, url, bus=bus, naive=naive)

    tasks = [asyncio.create_task(_bounded(v, u)) for v, u in pairs]

    for coro in asyncio.as_completed(tasks):
        result = await coro
        market.vendors.append(result)
        # Store partial snapshot on bus so GET /audit/{id}/results is always fresh
        bus.partial_result = market

    finalize_market(market)
    bus.partial_result = market
    bus.emit(TelemetryEvent(stage="market_done", vendor=None))
    return market
