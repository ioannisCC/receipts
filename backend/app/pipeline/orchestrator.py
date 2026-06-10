"""Per-vendor state machine + market-level batch runner.

URL -> [INGEST] -> [A: EXTRACT] -> per claim concurrent [B: HUNT] + [C: JUDGE]
                                -> [D: ADVISE] -> red-flag scan -> score -> VendorResult

Per-stage timeouts (asyncio.wait_for). Any stage failure degrades to a grey
state on that claim/vendor — audit_vendor() never raises."""

from __future__ import annotations

import asyncio

from app.config import settings
from app.pipeline.advise import advise
from app.pipeline.extract import extract
from app.pipeline.hunt import hunt
from app.pipeline.ingest import ingest
from app.pipeline.judge import judge
from app.pipeline.red_flag import detect as detect_red_flags, claim_quality_score
from app.schemas import (
    Claim,
    Evidence,
    Judgment,
    MarketResult,
    TelemetryEvent,
    VendorResult,
    Verdict,
)
from app.scoring import finalize_market, score_vendor
from app.telemetry import TelemetryBus


async def audit_vendor(
    vendor: str,
    url: str,
    *,
    bus: TelemetryBus,
    naive: bool = False,
) -> VendorResult:
    """Five-stage audit of a single vendor. Always returns a VendorResult.

    In naive mode the cheap-tier model is replaced with the premium tier
    everywhere and per-claim concurrency drops to 1 — same code path, no cascade.
    """
    cheap_tier: str = "premium" if naive else "cheap"
    sem_size = 1 if naive else max(1, settings.SEMAPHORE)
    sem = asyncio.Semaphore(sem_size)

    # 1) Ingest
    try:
        md = await asyncio.wait_for(
            ingest(url, bus=bus, vendor=vendor),
            timeout=settings.SCRAPE_TIMEOUT_S * 3 + 5,
        )
    except Exception:
        md = ""
    if not md or not md.strip():
        return VendorResult(vendor=vendor, url=url, status="unreachable")

    # 2) Extract
    try:
        claims: list[Claim] = await asyncio.wait_for(
            extract(md, bus=bus, vendor=vendor, tier=cheap_tier),  # type: ignore[arg-type]
            timeout=settings.LLM_TIMEOUT_S * 2,
        )
    except Exception:
        claims = []
    if not claims:
        return VendorResult(vendor=vendor, url=url, status="no_claims_extracted")

    # 3) Per-claim hunt + judge under the semaphore
    async def _one_claim(c: Claim) -> Judgment:
        async with sem:
            try:
                ev: Evidence = await asyncio.wait_for(
                    hunt(vendor, c, bus=bus),
                    timeout=settings.SCRAPE_TIMEOUT_S * 2 + 5,
                )
            except Exception:
                ev = Evidence(claim_id=c.claim_id, snippets=[], urls=[])
            try:
                j = await asyncio.wait_for(
                    judge(c, ev, bus=bus, naive=naive, vendor=vendor),
                    timeout=settings.LLM_TIMEOUT_S * 2 + 5,
                )
            except Exception:
                j = Judgment(
                    claim_id=c.claim_id,
                    verdict=Verdict.SELF_REPORTED_ONLY,
                    confidence=0.3,
                    rationale="judge stage failed; defaulted to SELF_REPORTED_ONLY",
                    receipts=[],
                    escalated=False,
                )
            return j

    judgments: list[Judgment] = await asyncio.gather(*[_one_claim(c) for c in claims])

    # 4) Advise
    try:
        advice = await asyncio.wait_for(
            advise(vendor, judgments, bus=bus, tier=cheap_tier),  # type: ignore[arg-type]
            timeout=settings.LLM_TIMEOUT_S,
        )
    except Exception:
        advice = ""

    # 5) Red-flag scan + score
    red_flags = detect_red_flags(claims)
    quality = claim_quality_score(claims, red_flags)
    score = score_vendor(judgments)

    result = VendorResult(
        vendor=vendor,
        url=url,
        status="ok",
        claims=list(claims),
        judgments=list(judgments),
        credibility_score=score,
        advice=advice,
        red_flags=red_flags,
        claim_quality_score=quality,
    )

    # Emit lifecycle event so the frontend can render the card immediately
    bus.emit(TelemetryEvent(
        stage="vendor_complete",
        vendor=vendor,
        payload=result.model_dump(mode="json"),
    ))

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
    """Run all vendors concurrently under a market-level semaphore."""
    urls = vendor_urls[:n] if n is not None else vendor_urls
    sem = asyncio.Semaphore(semaphore_size or settings.SEMAPHORE)
    market = MarketResult(category=category)

    async def _run(vendor: str, url: str):
        async with sem:
            return await audit_vendor(vendor, url, bus=bus, naive=naive)

    results = await asyncio.gather(
        *[_run(v, u) for v, u in urls], return_exceptions=True
    )

    for i, (vendor, url) in enumerate(urls):
        r = results[i]
        if isinstance(r, Exception):
            market.vendors.append(VendorResult(vendor=vendor, url=url, status="error"))
        else:
            market.vendors.append(r)

    finalize_market(market)

    bus.emit(TelemetryEvent(
        stage="market_complete",
        payload=market.model_dump(mode="json"),
    ))

    return market
