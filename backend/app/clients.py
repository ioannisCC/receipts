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
