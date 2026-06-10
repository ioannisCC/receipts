"""Stage B · HUNT. Per claim, 2 Tavily queries -> snippets + URLs.

This stage is TOOLS, not an LLM. Receipts are FOUND, never inferred.

We use Tavily search snippets only. We do NOT directly fetch G2/Capterra
review pages — they block automated requests — but their text is allowed
to appear via Tavily snippets.

Failover: on a primary-key error or rate-limit, retry once against the backup
key. Idempotent: cached by sha256(query) under caches/tavily/."""

from __future__ import annotations

import asyncio
from typing import Any

from tavily import AsyncTavilyClient

from app.cache import get as cache_get, set as cache_set
from app.config import settings
from app.schemas import Claim, Evidence
from app.telemetry import TelemetryBus, measure


_primary: AsyncTavilyClient | None = None
_backup: AsyncTavilyClient | None = None


def _client(backup: bool = False) -> AsyncTavilyClient | None:
    global _primary, _backup
    if backup:
        if not settings.TAVILY_API_KEY_BACKUP:
            return None
        if _backup is None:
            _backup = AsyncTavilyClient(settings.TAVILY_API_KEY_BACKUP)
        return _backup
    if not settings.TAVILY_API_KEY:
        return None
    if _primary is None:
        _primary = AsyncTavilyClient(settings.TAVILY_API_KEY)
    return _primary


async def _search(query: str) -> dict[str, Any] | None:
    cached = cache_get("tavily", query)
    if isinstance(cached, dict):
        return cached

    timeout = settings.SCRAPE_TIMEOUT_S
    for use_backup in (False, True):
        client = _client(backup=use_backup)
        if client is None:
            continue
        try:
            resp = await asyncio.wait_for(
                client.search(query, search_depth="basic", max_results=4),
                timeout=timeout,
            )
            if resp:
                cache_set("tavily", query, resp)
                return resp
        except Exception:
            continue
    return None


def _build_queries(vendor: str, claim: Claim) -> list[str]:
    metric = claim.metric or claim.claim
    return [
        f"{vendor} case study {metric}",
        f"{vendor} reviews results",
    ]


async def hunt(vendor: str, claim: Claim, *, bus: TelemetryBus) -> Evidence:
    snippets: list[str] = []
    urls: list[str] = []
    seen_urls: set[str] = set()

    for q in _build_queries(vendor, claim):
        async with measure(
            bus, stage="hunt", vendor=vendor, claim_id=claim.claim_id
        ) as _:
            resp = await _search(q)
        if not resp:
            continue
        for r in resp.get("results", [])[:4]:
            url = (r.get("url") or "").strip()
            content = (r.get("content") or "").strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                urls.append(url)
            if content:
                snippets.append(content[:600])

    return Evidence(claim_id=claim.claim_id, snippets=snippets, urls=urls)
