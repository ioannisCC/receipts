"""Drop a Magnific-generated image URL straight into the honest-ad cache.

Use this once you have an image URL from the Magnific MCP / dashboard /
wherever — the URL gets keyed by the exact (vendor, model, sorted SUPPORTED
claims) tuple the orchestrator uses to look it up, so the next sweep hits
the cache and never re-burns credits.

Usage:
    python scripts/cache_honest_ad.py Forethought "https://magnific.com/..."

If the SUPPORTED claims for the vendor have shifted since the last sweep,
run an audit first so the cache key matches what the live pipeline will
look up. This script re-derives the claims via a single-vendor audit (the
ingest + tavily caches keep it fast — about 5 seconds).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.honest_ad import (  # noqa: E402
    _cache_key,
    _supported_claim_texts,
    MAGNIFIC_MODEL,
)
from app.pipeline.orchestrator import run_market  # noqa: E402
from app.telemetry import TelemetryBus  # noqa: E402


VENDOR_URLS = {
    "Forethought": "https://forethought.ai",
    "Intercom Fin": "https://www.intercom.com/fin",
    "Decagon": "https://decagon.ai",
    "Zendesk AI": "https://www.zendesk.com/service/ai",
    "Tidio": "https://www.tidio.com",
    "Freshdesk AI": "https://www.freshworks.com/freshdesk",
    "Sierra": "https://sierra.ai/",
    "Ada": "https://www.ada.cx/",
}


async def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        print("\nKnown vendors:", ", ".join(sorted(VENDOR_URLS)))
        return 2

    vendor = sys.argv[1]
    url = sys.argv[2]

    if vendor not in VENDOR_URLS:
        print(f"unknown vendor: {vendor}\nknown: {sorted(VENDOR_URLS)}")
        return 2

    print(f"deriving current SUPPORTED claims for {vendor}…")
    bus = TelemetryBus()
    market = await run_market(
        "AI support agents",
        [(vendor, VENDOR_URLS[vendor])],
        bus=bus, naive=False, n=1,
    )
    v = market.vendors[0]
    if v.status != "ok":
        print(f"audit failed: status={v.status}")
        return 1

    supported = _supported_claim_texts(v)
    if not supported:
        print(f"{vendor} has 0 SUPPORTED claims this run — not a candidate.")
        return 1

    key = _cache_key(vendor, supported, MAGNIFIC_MODEL)
    cache_dir = Path(__file__).resolve().parents[1] / "app" / "caches" / "honest_ad"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{key}.json"

    payload = {"url": url, "claims": supported}
    cache_file.write_text(json.dumps(payload, indent=2))

    print(f"\n✓ cached")
    print(f"  vendor:    {vendor}")
    print(f"  model:     {MAGNIFIC_MODEL}")
    print(f"  claims:    {supported}")
    print(f"  cache key: {key}")
    print(f"  file:      {cache_file}")
    print(f"  url:       {url}")
    print(f"\nThe next audit will hit this cache for {vendor} — no Magnific call.")
    await asyncio.sleep(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
