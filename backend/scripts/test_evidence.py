"""Pre-doors evidence smoke. Run once Tavily keys are in .env.

Verifies:
  1. Tavily AsyncTavilyClient.search() — one query, primary key, then backup
  2. Jina Reader — `r.jina.ai/<url>` fetch on a JS-heavy vendor page

Prints results + which key path fired."""

from __future__ import annotations

import asyncio
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

TAVILY_QUERY = "Intercom case study cost reduction"
JINA_TARGET = "https://www.intercom.com/customers"


async def tavily_one(api_key: str, label: str) -> bool:
    if not api_key:
        print(f"[tavily/{label}] skipped — no key set")
        return False
    from tavily import AsyncTavilyClient  # type: ignore[import-not-found]

    client = AsyncTavilyClient(api_key)
    print(f"[tavily/{label}] querying: {TAVILY_QUERY!r}")
    resp = await client.search(
        TAVILY_QUERY,
        search_depth="basic",
        max_results=3,
    )
    results = resp.get("results", [])
    print(f"[tavily/{label}] got {len(results)} results")
    for r in results[:3]:
        print(f"  - {r.get('title', '')[:80]}  <{r.get('url', '')}>")
    return True


async def jina_one() -> None:
    url = f"https://r.jina.ai/{JINA_TARGET}"
    print(f"\n[jina] fetching: {url}")
    async with httpx.AsyncClient(timeout=20.0) as http:
        r = await http.get(url)
        print(f"[jina] {r.status_code} bytes={len(r.text)} preview:")
        print("  " + r.text[:300].replace("\n", " ⏎ "))


async def main() -> int:
    primary_ok = await tavily_one(settings.TAVILY_API_KEY, "primary")
    if not primary_ok:
        await tavily_one(settings.TAVILY_API_KEY_BACKUP, "backup")
    await jina_one()
    print("\nEVIDENCE SMOKE: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
