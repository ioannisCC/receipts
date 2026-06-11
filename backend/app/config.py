"""Pydantic-settings Settings(). Reads `.env`. No network at import time —
importing this module with `.env.example` values copied to `.env` must succeed."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    AKAMAI_INFERENCE_URL: str = "http://REPLACE_AT_KICKOFF:8080/v1"
    AKAMAI_TOKEN: str = ""
    CHEAP_MODEL: str = "Qwen/Qwen3-8B-FP8"

    ANTHROPIC_API_KEY: str = ""
    PREMIUM_MODEL: str = "claude-sonnet-4-6"

    TAVILY_API_KEY: str = ""
    TAVILY_API_KEY_BACKUP: str = ""

    N_VENDORS: int = 10
    SEMAPHORE: int = 8
    JUDGE_CONFIDENCE_THRESHOLD: float = 0.7
    SCRAPE_TIMEOUT_S: float = 10.0
    LLM_TIMEOUT_S: float = 45.0

    # Akamai fallback: route all cheap-tier calls to Anthropic when Akamai is unavailable.
    CHEAP_FALLBACK_TO_PREMIUM: bool = False

    # Magnific (Freepik) image gen — for the honest-ad stage. Eligibility floor:
    # using a second model family alongside Akamai-tier inference.
    FREEPIK_API_KEY: str = ""
    # Optional command for OAuth/MCP-backed image generation. It receives JSON on
    # stdin and must print either a URL or {"url": "..."} on stdout.
    HONEST_AD_IMAGE_COMMAND: str = ""
    HONEST_AD_TOP_N: int = 25


settings = Settings()
