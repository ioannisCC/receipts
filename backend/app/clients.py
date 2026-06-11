"""Two-tier LLM client. cheap=Akamai vLLM (OpenAI-compat), premium=Anthropic.

Boundary: messages-in, text+token-counts-out. We deliberately do NOT unify SDK-native
tool_use here — OpenAI and Anthropic tool schemas diverge enough that abstracting
them at this seam leaks complexity into every caller. Structured output for the
judge is done in the STAGE by prompting for JSON and pydantic-validating the parse.
A parse failure or low confidence on cheap-tier just escalates to premium — the
cascade is the safety net."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import settings


Tier = Literal["cheap", "premium"]


# COST TABLE — verified at platform.claude.com on 2026-06-10.
# Sonnet 4.6: $3 / MTok input, $15 / MTok output (base, no cache, no batch).
# Cheap tier is imputed, not provider-billed: it gives the dashboard a small
# visible infrastructure cost even when the Akamai endpoint is running on credits.
COST_TABLE: dict[str, dict[str, float]] = {
    settings.CHEAP_MODEL: {
        "input_per_mtok": settings.CHEAP_INPUT_PER_MTOK,
        "output_per_mtok": settings.CHEAP_OUTPUT_PER_MTOK,
    },
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


def attempt_cost_usd(model: str) -> float:
    if model == settings.CHEAP_MODEL:
        return settings.CHEAP_ATTEMPT_COST_USD
    return 0.0


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
            max_retries=0,
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
    if tier == "cheap" and settings.CHEAP_FALLBACK_TO_PREMIUM:
        tier = "premium"

    if timeout_s is not None:
        timeout = timeout_s
    elif tier == "cheap":
        timeout = min(settings.LLM_TIMEOUT_S, settings.CHEAP_LLM_TIMEOUT_S)
    else:
        timeout = settings.LLM_TIMEOUT_S

    if tier == "cheap":
        model = settings.CHEAP_MODEL
        # Qwen3 thinking mode must be disabled via /no_think in the system prompt.
        no_think_messages = []
        injected = False
        for m in messages:
            if m["role"] == "system" and not injected:
                no_think_messages.append({**m, "content": "/no_think\n" + m["content"]})
                injected = True
            else:
                no_think_messages.append(m)
        if not injected:
            no_think_messages.insert(0, {"role": "system", "content": "/no_think"})
        resp = await asyncio.wait_for(
            cheap_client().chat.completions.create(
                model=model,
                messages=no_think_messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            ),
            timeout=timeout + 0.5,
        )
        msg = resp.choices[0].message if resp.choices else None
        text = (msg.content or "") if msg else ""
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
