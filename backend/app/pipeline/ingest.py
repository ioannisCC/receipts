"""Stage INGEST. URL -> clean markdown text.

Primary: httpx GET + trafilatura.extract. Fallback: Jina Reader (r.jina.ai/<url>)
for JS-heavy pages. Hard fail -> empty string; the orchestrator grey-cards the
vendor (status='unreachable'). Failure is a STATE, never a propagated exception.

Idempotent: cached by sha256(url) under caches/ingest/."""

from __future__ import annotations

import asyncio

import httpx
import trafilatura

from app.cache import get as cache_get, set as cache_set
from app.config import settings
from app.telemetry import TelemetryBus, measure


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Receipts/0.1"
)


async def _fetch(url: str, timeout: float) -> str | None:
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as http:
        r = await http.get(url)
        if r.status_code != 200 or not r.text:
            return None
        return r.text


def _to_markdown(html: str) -> str:
    md = trafilatura.extract(
        html,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )
    return (md or "").strip()


async def _jina_fallback(url: str, timeout: float) -> str:
    jina_url = f"https://r.jina.ai/{url}"
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/markdown"},
    ) as http:
        r = await http.get(jina_url)
        if r.status_code != 200:
            return ""
        return (r.text or "").strip()


async def ingest(url: str, *, bus: TelemetryBus, vendor: str | None = None) -> str:
    """Fetch + clean. Returns empty string on total failure (no exceptions leak)."""
    cached = cache_get("ingest", url)
    if isinstance(cached, str) and cached:
        async with measure(bus, stage="ingest", vendor=vendor) as m:
            m.tokens_in = 0
            m.tokens_out = 0
        return cached

    timeout = settings.SCRAPE_TIMEOUT_S
    md = ""

    async with measure(bus, stage="ingest", vendor=vendor) as m:
        # 1) primary: httpx + trafilatura
        try:
            html = await asyncio.wait_for(_fetch(url, timeout), timeout=timeout + 1)
            if html:
                md = _to_markdown(html)
        except Exception:
            md = ""

        # 2) fallback: Jina Reader (JS-heavy pages, anti-bot pages).
        # Vendor homepages are JS-heavy enough that trafilatura usually
        # under-extracts; always run Jina in parallel-like fashion and keep
        # whichever is longer. The few hundred extra ms are worth the signal.
        if len(md) < 3000:
            try:
                jmd = await asyncio.wait_for(
                    _jina_fallback(url, timeout * 2), timeout=timeout * 2 + 1
                )
                if jmd and len(jmd) > len(md):
                    md = jmd
            except Exception:
                pass

        m.tokens_in = 0
        m.tokens_out = len(md)  # bytes-of-text as a soft proxy on the dashboard

    if md:
        cache_set("ingest", url, md)
    return md
