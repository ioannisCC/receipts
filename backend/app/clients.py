"""Two-tier LLM client. cheap=Akamai vLLM (OpenAI-compat), premium=Anthropic.

Boundary: messages-in, text+token-counts-out. We deliberately do NOT unify SDK-native
tool_use here — OpenAI and Anthropic tool schemas diverge enough that abstracting
them at this seam leaks complexity into every caller. Structured output is done in
the STAGE by prompting for JSON and pydantic-validating the parse via the
`call_and_parse_json` helper below. A parse failure or low confidence on cheap-tier
just escalates to premium — the cascade is the safety net."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import settings
from app.telemetry import TelemetryBus, measure


Tier = Literal["cheap", "premium"]


# COST TABLE — verified at platform.claude.com on 2026-06-10.
# Sonnet 4.6: $3 / MTok input, $15 / MTok output.
# Haiku 4.5:  $1 / MTok input, $5  / MTok output  (temp cheap-tier proxy).
# Qwen3-8B-FP8 (real Akamai cheap tier) is imputed at $0.0: on hackathon credits
# the marginal per-token cost is zero — the honest framing and the framing that
# maximizes race-screen contrast when the swap lands.
COST_TABLE: dict[str, dict[str, float]] = {
    "Qwen/Qwen3-8B-FP8": {"input_per_mtok": 0.0, "output_per_mtok": 0.0},
    "claude-haiku-4-5-20251001": {"input_per_mtok": 1.0, "output_per_mtok": 5.0},
    "claude-haiku-4-5": {"input_per_mtok": 1.0, "output_per_mtok": 5.0},
    "claude-sonnet-4-6": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},
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


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _try_parse_json(text: str) -> Any | None:
    """Best-effort JSON extraction. Direct parse first, then strip a code fence,
    then carve out the first {...} or [...] span."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        i = text.find(open_ch)
        j = text.rfind(close_ch)
        if 0 <= i < j:
            try:
                return json.loads(text[i : j + 1])
            except Exception:
                continue
    return None


async def call_and_parse_json(
    bus: TelemetryBus,
    *,
    messages: list[dict[str, str]],
    tier: Tier,
    stage: str,
    vendor: Optional[str] = None,
    claim_id: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    timeout_s: Optional[float] = None,
    escalated: bool = False,
) -> tuple[str, Any | None]:
    """Single LLM call wrapped in measure(), JSON-parsed, with one retry on parse
    failure ("JSON only, no commentary" reminder). Returns (raw_text, parsed_or_None).

    The retry counts as its own telemetry event — both calls show up in the demo
    stream. Caller passes `escalated=True` when this is the cascade's premium-tier
    fallback after a cheap-tier miss."""
    model_name = settings.CHEAP_MODEL if tier == "cheap" else settings.PREMIUM_MODEL

    async with measure(
        bus, stage=stage, model=model_name, vendor=vendor, claim_id=claim_id
    ) as m:
        m.escalated = escalated
        result = await chat(
            tier,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=timeout_s,
        )
        m.tokens_in = result.tokens_in
        m.tokens_out = result.tokens_out
        m.cost_usd = cost_usd(model_name, result.tokens_in, result.tokens_out)

    parsed = _try_parse_json(result.text)
    if parsed is not None:
        return result.text, parsed

    retry_messages = list(messages) + [
        {"role": "assistant", "content": result.text},
        {
            "role": "user",
            "content": (
                "Your previous response was not valid JSON. "
                "Output ONLY the JSON value, with no prose, no markdown, no code fence."
            ),
        },
    ]
    async with measure(
        bus, stage=stage, model=model_name, vendor=vendor, claim_id=claim_id
    ) as m:
        m.escalated = escalated
        result2 = await chat(
            tier,
            retry_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=timeout_s,
        )
        m.tokens_in = result2.tokens_in
        m.tokens_out = result2.tokens_out
        m.cost_usd = cost_usd(model_name, result2.tokens_in, result2.tokens_out)

    parsed2 = _try_parse_json(result2.text)
    return result2.text, parsed2
