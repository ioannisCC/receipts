"""Pydantic schemas for every pipeline stage. Schemas-first: no stage emits an
unvalidated dict. The Verdict enum is intentionally narrow — we measure public
substantiation, never truth."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    """The verdict enum is exactly these three values.

    We never label a claim false — we report only what was found in public sources.
    Empty/insufficient search results default to SELF_REPORTED_ONLY (the claim exists
    only in the vendor's own marketing). NO_PUBLIC_RECEIPT_FOUND is reserved for
    claims where evidence was actively searched and was conspicuously absent or
    contradicted.
    """

    SUPPORTED = "SUPPORTED"
    SELF_REPORTED_ONLY = "SELF_REPORTED_ONLY"
    NO_PUBLIC_RECEIPT_FOUND = "NO_PUBLIC_RECEIPT_FOUND"


class Claim(BaseModel):
    """Atomic, decomposable outcome claim extracted from a vendor's page."""

    claim_id: str
    claim: str
    metric: Optional[str] = None
    magnitude: Optional[str] = None
    claim_type: str
    verbatim_span: str


class Evidence(BaseModel):
    """Search-derived evidence for a single claim. Snippets and URLs are FOUND
    (Tavily search), never inferred."""

    claim_id: str
    snippets: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class Judgment(BaseModel):
    """Verdict + confidence + receipts for a single claim. `escalated=True` means
    the cheap-tier judge fell below the confidence threshold and the call was
    re-issued against the premium tier."""

    claim_id: str
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    receipts: list[str] = Field(default_factory=list)
    escalated: bool = False


class VendorResult(BaseModel):
    """One vendor's full audit result. `status` carries the per-vendor pipeline
    state (e.g. 'ok', 'unreachable', 'no_claims_extracted') so grey-card failures
    are first-class, not exceptions."""

    vendor: str
    url: str
    status: str
    claims: list[Claim] = Field(default_factory=list)
    judgments: list[Judgment] = Field(default_factory=list)
    credibility_score: Optional[float] = None
    advice: Optional[str] = None


class MarketResult(BaseModel):
    """Aggregate result for a whole category sweep. The Claim Inflation Index
    needs N>=25 vendors to read as an index rather than an anecdote."""

    category: str
    vendors: list[VendorResult] = Field(default_factory=list)
    claim_inflation_index: float = 0.0
    telemetry_summary: dict[str, Any] = Field(default_factory=dict)


class TelemetryEvent(BaseModel):
    """One measured external call. Every LLM / search / scrape call MUST emit
    one of these via the telemetry wrapper. The telemetry IS the demo —
    fabricating any field ends the project's credibility."""

    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stage: str
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    ttft_ms: Optional[float] = None
    cost_usd: float = 0.0
    escalated: bool = False
    vendor: Optional[str] = None
    claim_id: Optional[str] = None
