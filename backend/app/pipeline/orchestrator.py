"""Per-vendor state machine. Batch loop is a later dispatch.

URL -> [INGEST] -> [A: EXTRACT] -> per claim concurrent [B: HUNT] + [C: JUDGE]
                                -> [D: ADVISE] -> score -> VendorResult

Per-stage timeouts (asyncio.wait_for). Any stage failure degrades to a grey
state on that claim/vendor — the audit_vendor() call never raises."""

from __future__ import annotations

import asyncio

from app.config import settings
from app.schemas import (
    Claim,
    Evidence,
    Judgment,
    MarketResult,
    VendorResult,
    Verdict,
)
from app.scoring import score_vendor
from app.telemetry import TelemetryBus

from app.pipeline.advise import advise
from app.pipeline.extract import extract
from app.pipeline.hunt import hunt
from app.pipeline.ingest import ingest
from app.pipeline.judge import judge


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

    # 5) Score
    score = score_vendor(judgments)

    return VendorResult(
        vendor=vendor,
        url=url,
        status="ok",
        claims=list(claims),
        judgments=list(judgments),
        credibility_score=score,
        advice=advice,
    )


async def run_market(
    category: str,
    vendor_urls: list[tuple[str, str]],
    *,
    bus: TelemetryBus,
    naive: bool = False,
    n: int | None = None,
    semaphore_size: int | None = None,
) -> MarketResult:
    """Batch loop is a later dispatch — current implementation runs single vendors
    sequentially for testing the server surface."""
    raise NotImplementedError("batch loop — next dispatch")
