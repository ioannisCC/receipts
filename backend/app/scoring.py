"""Score claims into a vendor credibility number, and roll up vendor scores into
the category-wide Claim Inflation Index. The Index needs N>=25 vendors to read
as an index rather than an anecdote (CLAUDE.md)."""

from __future__ import annotations

from app.schemas import Judgment, MarketResult, VendorResult, Verdict


VERDICT_WEIGHT: dict[Verdict, float] = {
    Verdict.SUPPORTED: 1.0,
    Verdict.SELF_REPORTED_ONLY: 0.4,
    Verdict.NO_PUBLIC_RECEIPT_FOUND: 0.0,
}


def vendor_credibility(judgments: list[Judgment]) -> float | None:
    """Weighted average of per-claim verdicts, in [0, 1]. Returns None when there
    is nothing to score yet (no claims extracted, or vendor unreachable)."""
    if not judgments:
        return None
    total = sum(VERDICT_WEIGHT[j.verdict] for j in judgments)
    return total / len(judgments)


def claim_inflation_index(vendors: list[VendorResult]) -> float:
    """Category-level inflation: how many claims, on average, are made vs. how
    many are publicly substantiated. Higher = more puffery in the category."""
    scored = [v for v in vendors if v.judgments]
    if not scored:
        return 0.0
    inflations = []
    for v in scored:
        n_claims = len(v.judgments)
        n_supported = sum(1 for j in v.judgments if j.verdict == Verdict.SUPPORTED)
        if n_claims == 0:
            continue
        inflations.append(n_claims / max(n_supported, 1))
    if not inflations:
        return 0.0
    return sum(inflations) / len(inflations)


def finalize_market(result: MarketResult) -> MarketResult:
    for v in result.vendors:
        v.credibility_score = vendor_credibility(v.judgments)
    result.claim_inflation_index = claim_inflation_index(result.vendors)
    return result
