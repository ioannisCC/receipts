"""Run the full single-vendor pipeline against ONE real vendor.

Hardcoded inputs (transparent):
    vendor = "Intercom Fin"
    url    = "https://www.intercom.com/fin"
    naive  = False
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orjson  # noqa: E402

from app.pipeline.orchestrator import audit_vendor  # noqa: E402
from app.telemetry import TelemetryBus  # noqa: E402


VENDOR = "Intercom Fin"
URL = "https://www.intercom.com/fin"


async def main() -> int:
    bus = TelemetryBus()
    print(f"=== AUDIT_VENDOR run_id={bus.run_id} ===")
    t0 = time.perf_counter()
    result = await audit_vendor(VENDOR, URL, bus=bus, naive=False)
    elapsed = time.perf_counter() - t0

    print(f"\n=== RESULT in {elapsed:.1f}s ===")
    print(f"vendor:      {result.vendor}")
    print(f"url:         {result.url}")
    print(f"status:      {result.status}")
    print(f"score:       {result.credibility_score}")
    print(f"#claims:     {len(result.claims)}")
    print(f"#judgments:  {len(result.judgments)}")

    spread: dict[str, int] = {}
    n_escalated = 0
    for j in result.judgments:
        spread[j.verdict.value] = spread.get(j.verdict.value, 0) + 1
        if j.escalated:
            n_escalated += 1
    print(f"verdict spread: {spread}")
    print(f"escalated:      {n_escalated} / {len(result.judgments)} judgments")

    print("\n=== CLAIMS ===")
    for c, j in zip(result.claims, result.judgments):
        print(
            f"- [{j.verdict.value} conf={j.confidence:.2f} esc={j.escalated}] "
            f"{c.claim[:120]}"
        )
        if j.receipts:
            print(f"    receipts: {j.receipts[:2]}")

    print("\n=== ADVICE ===")
    print(result.advice or "(none)")

    log_path = Path(__file__).resolve().parents[1] / "app" / "logs" / f"run_{bus.run_id}.jsonl"
    print(f"\n=== TELEMETRY LOG at {log_path} ===")
    if log_path.exists():
        lines = log_path.read_bytes().splitlines()
        print(f"events: {len(lines)}")
        if lines:
            print("first event:")
            print(orjson.dumps(orjson.loads(lines[0]), option=orjson.OPT_INDENT_2).decode())

    # short delay to let any pending emit_async tasks flush, then exit
    await asyncio.sleep(0.3)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
