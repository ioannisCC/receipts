"""Stage E · HONEST AD. Magnific Mystic backdrop + structured claim overlay.

The eligibility-floor stage: every other stage uses Akamai-tier LLM inference;
this one uses a second model family (Magnific image gen). That's the "more
than one model" bar the project clears.

What this stage actually does:
    1. Take ONLY the vendor's SUPPORTED judgments (after the receipt-consistency
       guard those are the genuinely-corroborated claims).
    2. Generate ONE clean ad-style background image via Magnific. The image
       has generous negative space and NO text/numbers — claim figures stay
       structured and get overlaid in React.
    3. Cache by sha256(vendor + sorted(supported_claims) + model). Re-runs reuse
       the cached URL. Magnific credits are finite.

Zero supported claims → return (None, []). The card shows a stark honest state."""

from __future__ import annotations

import hashlib
import time
from typing import Optional

from app.cache import get as cache_get, set as cache_set
from app.clients import MAGNIFIC_CREDIT_ESTIMATE, generate_image
from app.schemas import TelemetryEvent, VendorResult, Verdict
from app.telemetry import TelemetryBus


# Vendor-neutral prompt — Magnific never sees the claim figures, so it can't
# typeset them wrong. The figures land as DOM text in React (App.tsx overlay).
_PROMPT_TEMPLATE = """A premium editorial marketing backdrop for {vendor}, a polished B2B software company.

Composition: clean, modern, generous negative space in the upper third for headline text to be overlaid later. Centered focal area, balanced framing.

Style: photorealistic, magazine-quality, soft natural studio lighting, Apple-or-Stripe aesthetic. Abstract subtle gradient or out-of-focus modern office environment. Premium, calm, confident.

CRITICAL: absolutely NO text, NO words, NO numbers, NO logos, NO typography of any kind anywhere in the image. Just a beautiful brand-neutral premium background ready for overlay."""


MAGNIFIC_MODEL = "realism"
MAGNIFIC_RESOLUTION = "1k"
MAGNIFIC_ASPECT = "widescreen_16_9"


def _supported_claim_texts(vendor: VendorResult) -> list[str]:
    """The exact claim strings the vendor can publicly substantiate. Returned
    as a list of plain strings — React overlays these as DOM text."""
    claim_by_id = {c.claim_id: c for c in vendor.claims}
    out: list[str] = []
    for j in vendor.judgments:
        if j.verdict == Verdict.SUPPORTED and j.claim_id in claim_by_id:
            text = (claim_by_id[j.claim_id].claim or "").strip()
            if text and text not in out:
                out.append(text)
    return out


def _cache_key(vendor_name: str, supported_claims: list[str], model: str) -> str:
    payload = "|".join([vendor_name, model] + sorted(supported_claims))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def generate_honest_ad(
    vendor: VendorResult, *, bus: TelemetryBus
) -> tuple[Optional[str], list[str]]:
    """Returns (honest_ad_url, supported_claim_texts).
      - (url, [claims])  on success or cache hit
      - (None, [])       if vendor has zero SUPPORTED claims
      - (None, [claims]) if Magnific failed but we still want to show the
        stark honest state with the real claim text"""
    supported = _supported_claim_texts(vendor)
    if not supported:
        return None, []

    key = _cache_key(vendor.vendor, supported, MAGNIFIC_MODEL)

    # Cache hit: emit a lightweight telemetry event so the dashboard shows the
    # stage fired, but with zero latency + zero credits — proves cache savings.
    cached = cache_get("honest_ad", key)
    if isinstance(cached, dict) and cached.get("url"):
        bus.emit(
            TelemetryEvent(
                stage="honest_ad",
                vendor=vendor.vendor,
                latency_ms=0.0,
                payload={
                    "cache": "hit",
                    "model": MAGNIFIC_MODEL,
                    "resolution": MAGNIFIC_RESOLUTION,
                    "credits_estimated": 0,
                    "n_supported_claims": len(supported),
                },
            )
        )
        return str(cached["url"]), supported

    prompt = _PROMPT_TEMPLATE.format(vendor=vendor.vendor)

    t0 = time.perf_counter()
    url = await generate_image(
        prompt,
        model=MAGNIFIC_MODEL,
        resolution=MAGNIFIC_RESOLUTION,
        aspect_ratio=MAGNIFIC_ASPECT,
        timeout_s=60.0,
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    credits = MAGNIFIC_CREDIT_ESTIMATE.get(MAGNIFIC_RESOLUTION, 0)
    bus.emit(
        TelemetryEvent(
            stage="honest_ad",
            vendor=vendor.vendor,
            latency_ms=latency_ms,
            payload={
                "cache": "miss",
                "model": MAGNIFIC_MODEL,
                "resolution": MAGNIFIC_RESOLUTION,
                "aspect_ratio": MAGNIFIC_ASPECT,
                "credits_estimated": credits,
                "n_supported_claims": len(supported),
                "ok": url is not None,
            },
        )
    )

    if url:
        cache_set("honest_ad", key, {"url": url, "claims": supported})
        return url, supported

    # Magnific failed — return the claims anyway so the card can show the stark
    # honest state ("we found these substantiated claims; ad failed to render").
    return None, supported


def pick_ad_candidates(
    vendors: list[VendorResult], *, top_n: int
) -> list[VendorResult]:
    """Pick vendors with the BIGGEST gap between claims-made and supported, but
    NOT zero-supported. A 'claims 9, can show 3' poster beats a blank one — and
    a blank ad with a real vendor's name is legally provocative in a way that
    burns credits without earning demo value."""
    def n_supported(v: VendorResult) -> int:
        return sum(1 for j in v.judgments if j.verdict == Verdict.SUPPORTED)

    eligible = [v for v in vendors if n_supported(v) > 0]
    eligible.sort(key=lambda v: len(v.judgments) - n_supported(v), reverse=True)
    return eligible[: max(0, top_n)]
