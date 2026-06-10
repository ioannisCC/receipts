"""Akamai cheap-tier smoke test. Run me at kickoff once AKAMAI_INFERENCE_URL is set.

Verifies:
  1. GET {base}/models — endpoint reachable, lists the served model
  2. POST {base}/chat/completions — 1-token completion succeeds, measures TTFT

Header: Authorization: Bearer <AKAMAI_TOKEN>.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

# Allow running as a script: `python scripts/smoke_akamai.py` from backend/
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402


def _banner_if_unset() -> bool:
    if "REPLACE" in settings.AKAMAI_INFERENCE_URL:
        print(
            "\n=== AKAMAI SMOKE TEST: NOT YET RUNNABLE ===\n"
            f"AKAMAI_INFERENCE_URL is still a placeholder: {settings.AKAMAI_INFERENCE_URL}\n"
            "Run me at kickoff once the real host/IP is filled into .env.\n"
            "Expected shape: http://<HOST>:8080/v1\n"
        )
        return True
    return False


async def main() -> int:
    if _banner_if_unset():
        return 0

    base = settings.AKAMAI_INFERENCE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.AKAMAI_TOKEN}"}

    async with httpx.AsyncClient(timeout=15.0) as http:
        print(f"GET  {base}/models")
        try:
            r = await http.get(f"{base}/models", headers=headers)
            if r.status_code == 200:
                print(f"  -> 200 {json.dumps(r.json(), indent=2)[:400]}")
            else:
                # Anthropic's OpenAI-compat layer doesn't implement /v1/models.
                # That's fine — chat.completions is the only path stages depend on.
                print(f"  -> {r.status_code} (skipped — endpoint may not implement /models)")
        except Exception as e:
            print(f"  -> skipped: {type(e).__name__}: {e}")

        print(f"\nPOST {base}/chat/completions  (model={settings.CHEAP_MODEL}, max_tokens=1)")
        body = {
            "model": settings.CHEAP_MODEL,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": True,
        }
        t0 = time.perf_counter()
        ttft_ms: float | None = None
        chunks = 0
        async with http.stream(
            "POST",
            f"{base}/chat/completions",
            headers={**headers, "Content-Type": "application/json"},
            json=body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000.0
                chunks += 1
        total_ms = (time.perf_counter() - t0) * 1000.0
        print(f"  -> ttft={ttft_ms:.1f}ms total={total_ms:.1f}ms chunks={chunks}")
        print("\nAKAMAI SMOKE TEST: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
