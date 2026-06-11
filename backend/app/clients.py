"""Two-tier LLM client. cheap=Akamai vLLM (OpenAI-compat), premium=Anthropic.

Boundary: messages-in, text+token-counts-out. We deliberately do NOT unify SDK-native
tool_use here — OpenAI and Anthropic tool schemas diverge enough that abstracting
them at this seam leaks complexity into every caller. Structured output for the
judge is done in the STAGE by prompting for JSON and pydantic-validating the parse.
A parse failure or low confidence on cheap-tier just escalates to premium — the
cascade is the safety net."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

import orjson
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import settings


Tier = Literal["cheap", "premium"]


# COST TABLE — verified at platform.claude.com on 2026-06-10.
# Sonnet 4.6: $3 / MTok input, $15 / MTok output (base, no cache, no batch).
# Cheap tier (Akamai/Qwen3-8B-FP8 on shared vLLM cluster) is imputed at $0.0 per
# token: on hackathon credits / our GPU the marginal per-token cost is zero. This
# is the honest framing AND it maximizes race-screen contrast — premium burns real
# dollars on stage, cheap does not.
COST_TABLE: dict[str, dict[str, float]] = {
    settings.CHEAP_MODEL: {"input_per_mtok": 0.0, "output_per_mtok": 0.0},
    settings.PREMIUM_MODEL: {"input_per_mtok": 3.0, "output_per_mtok": 15.0},
}


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    rates = COST_TABLE.get(model)
    if rates is None:
        return 0.0
    return (
        tokens_in / 1_000_000.0 * rates["input_per_mtok"]
        + tokens_out / 1_000_000.0 * rates["output_per_mtok"]
    )


@dataclass
class ChatResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    tier: Tier
    raw: Any = None


_cheap_client: Optional[AsyncOpenAI] = None
_premium_client: Optional[AsyncAnthropic] = None


def cheap_client() -> AsyncOpenAI:
    global _cheap_client
    if _cheap_client is None:
        _cheap_client = AsyncOpenAI(
            base_url=settings.AKAMAI_INFERENCE_URL,
            api_key=settings.AKAMAI_TOKEN,
        )
    return _cheap_client


def premium_client() -> AsyncAnthropic:
    global _premium_client
    if _premium_client is None:
        _premium_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _premium_client


async def chat(
    tier: Tier,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout_s: Optional[float] = None,
) -> ChatResult:
    """Unified messages-in / text+usage-out entrypoint. Both tiers go through here
    so the telemetry wrapper has ONE surface to instrument. Messages use the
    OpenAI shape: [{"role": "system"|"user"|"assistant", "content": "..."}]."""
    timeout = timeout_s if timeout_s is not None else settings.LLM_TIMEOUT_S

    if tier == "cheap" and settings.CHEAP_FALLBACK_TO_PREMIUM:
        tier = "premium"

    if tier == "cheap":
        model = settings.CHEAP_MODEL
        resp = await cheap_client().chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        usage = resp.usage
        return ChatResult(
            text=text,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
            model=model,
            tier="cheap",
            raw=resp,
        )

    # premium — Anthropic. Split out system message; Anthropic takes it separately.
    model = settings.PREMIUM_MODEL
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    convo = [m for m in messages if m["role"] != "system"]
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": convo,
    }
    if system_parts:
        kwargs["system"] = "\n\n".join(system_parts)
    resp = await premium_client().messages.create(**kwargs, timeout=timeout)
    # Anthropic returns a list of content blocks; concatenate text blocks.
    text = "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    )
    return ChatResult(
        text=text,
        tokens_in=resp.usage.input_tokens,
        tokens_out=resp.usage.output_tokens,
        model=model,
        tier="premium",
        raw=resp,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Magnific image generation — ADDITIVE. chat() above stays byte-identical.
# ─────────────────────────────────────────────────────────────────────────────

# Docs (2026-06-10): https://docs.magnific.com/api-reference/mystic/post-mystic
# POST  https://api.magnific.com/v1/ai/mystic           → {data:{task_id, status}}
# GET   https://api.magnific.com/v1/ai/mystic/{task_id} → {data:{status, generated:[url]}}
# Header drift from the dispatch: docs say x-magnific-api-key (we use that), the
# dispatch said x-freepik-api-key. Env var name stays FREEPIK_API_KEY (Freepik
# owns Magnific; many users hold one key for both ecosystems).
MAGNIFIC_BASE = "https://api.magnific.com/v1/ai/mystic"

# Credits per generation — rough estimate (docs don't publish a credit table).
# Mystic at 1k/widescreen ≈ 25 credits. Recorded in telemetry payload so we can
# correct this once we see real billing.
MAGNIFIC_CREDIT_ESTIMATE: dict[str, int] = {"1k": 25, "2k": 50, "4k": 100}


async def generate_image(
    prompt: str,
    *,
    model: str = "realism",
    resolution: str = "1k",
    aspect_ratio: str = "widescreen_16_9",
    timeout_s: float = 60.0,
    poll_interval_s: float = 1.5,
) -> Optional[str]:
    """Magnific Mystic text-to-image. Returns the first image URL on COMPLETED,
    or None on failure / timeout / missing key. Never raises.

    The caller is responsible for telemetry wrapping (so the stage name is the
    caller's, not generic 'magnific') and for caching."""
    bridge_url = await _generate_image_via_command(
        prompt,
        model=model,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        timeout_s=timeout_s,
    )
    if bridge_url:
        return bridge_url

    import httpx

    api_key = settings.FREEPIK_API_KEY
    if not api_key:
        return None

    headers = {"x-magnific-api-key": api_key, "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "prompt": prompt,
        "model": model,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(MAGNIFIC_BASE, headers=headers, json=body)
            if r.status_code >= 400:
                return None
            task_id = (r.json().get("data") or {}).get("task_id")
            if not task_id:
                return None

            deadline = timeout_s
            elapsed = 0.0
            while elapsed < deadline:
                await _sleep(poll_interval_s)
                elapsed += poll_interval_s
                pr = await http.get(f"{MAGNIFIC_BASE}/{task_id}", headers=headers)
                if pr.status_code >= 400:
                    continue
                data = (pr.json().get("data") or {})
                status = data.get("status")
                if status == "COMPLETED":
                    gen = data.get("generated") or []
                    return gen[0] if gen else None
                if status == "FAILED":
                    return None
            return None
    except Exception:
        return None


async def _sleep(s: float) -> None:
    import asyncio as _a
    await _a.sleep(s)


async def _generate_image_via_command(
    prompt: str,
    *,
    model: str,
    resolution: str,
    aspect_ratio: str,
    timeout_s: float,
) -> Optional[str]:
    """Bridge for OAuth/MCP image generators.

    HONEST_AD_IMAGE_COMMAND lets the live app call a local MCP helper without
    baking Codex's tool runtime into FastAPI. The command receives JSON on
    stdin and should print either a URL or JSON containing a URL.
    """
    command = settings.HONEST_AD_IMAGE_COMMAND.strip()
    if not command:
        return None

    import asyncio
    import re
    import shlex

    body = {
        "prompt": prompt,
        "model": model,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "timeout_s": timeout_s,
    }

    try:
        args = shlex.split(command)
        if not args:
            return None
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(
            proc.communicate(orjson.dumps(body)),
            timeout=timeout_s,
        )
        if proc.returncode != 0:
            return None

        text = stdout.decode("utf-8", errors="ignore").strip()
        if not text:
            return None

        try:
            parsed = orjson.loads(text)
            found = _find_url(parsed)
            if found:
                return found
        except Exception:
            pass

        match = re.search(r"https?://\\S+", text)
        return match.group(0).strip('",') if match else None
    except Exception:
        return None


def _find_url(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value if value.startswith(("http://", "https://")) else None
    if isinstance(value, list):
        for item in value:
            found = _find_url(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("url", "image_url", "output_url"):
            found = _find_url(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _find_url(item)
            if found:
                return found
    return None
