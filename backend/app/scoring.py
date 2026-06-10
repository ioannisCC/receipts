"""Score claims into a vendor credibility number, and roll up vendor scores into
the category-wide Claim Inflation Index. The Index needs N>=25 vendors to read
as an index rather than an anecdote (CLAUDE.md)."""

from __future__ import annotations

import re
from collections import defaultdict

from app.schemas import ClusterGroup, Judgment, MarketResult, VendorResult, Verdict


VERDICT_WEIGHT: dict[Verdict, float] = {
    Verdict.SUPPORTED: 1.0,
    Verdict.SELF_REPORTED_ONLY: 0.4,
    Verdict.NO_PUBLIC_RECEIPT_FOUND: 0.0,
}


def score_vendor(judgments: list[Judgment]) -> float | None:
    if not judgments:
        return None
    total = sum(VERDICT_WEIGHT[j.verdict] for j in judgments)
    return round(total / len(judgments), 3)


vendor_credibility = score_vendor


def claim_inflation_index(vendors: list[VendorResult]) -> float:
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
    return round(sum(inflations) / len(inflations), 2)


def _normalize_metric(raw: str) -> str:
    raw = raw.lower().strip()
    for word in ("the", "a", "an", "our", "their", "its", "your"):
        raw = re.sub(rf"\b{word}\b\s*", "", raw)
    return " ".join(raw.split()) or "general"


def cluster_claims(vendors: list[VendorResult]) -> list[ClusterGroup]:
    """Group claims across vendors by normalised metric. Returns groups with ≥2 vendors."""
    groups: dict[str, dict] = defaultdict(lambda: {
        "vendors": [], "supported": 0, "self_reported": 0, "no_receipt": 0,
    })

    for v in vendors:
        for claim, judgment in zip(v.claims, v.judgments):
            key = _normalize_metric(claim.metric or claim.claim_type or "general")
            g = groups[key]
            if v.vendor not in g["vendors"]:
                g["vendors"].append(v.vendor)
            if judgment.verdict == Verdict.SUPPORTED:
                g["supported"] += 1
            elif judgment.verdict == Verdict.SELF_REPORTED_ONLY:
                g["self_reported"] += 1
            else:
                g["no_receipt"] += 1

    clusters = []
    for metric, g in sorted(groups.items(), key=lambda x: -len(x[1]["vendors"])):
        if len(g["vendors"]) < 2:
            continue
        total = g["supported"] + g["self_reported"] + g["no_receipt"]
        clusters.append(ClusterGroup(
            metric=metric,
            count=total,
            vendors=g["vendors"],
            supported=g["supported"],
            self_reported=g["self_reported"],
            no_receipt=g["no_receipt"],
        ))
    return clusters


def build_benchmark(vendors: list[VendorResult]) -> dict:
    scored = [v for v in vendors if v.credibility_score is not None]
    if not scored:
        return {}
    scores = [v.credibility_score for v in scored]  # type: ignore[misc]
    best = max(scored, key=lambda v: v.credibility_score or 0)
    worst = min(scored, key=lambda v: v.credibility_score or 1)
    all_j = [j for v in vendors for j in v.judgments]
    n_supported = sum(1 for j in all_j if j.verdict == Verdict.SUPPORTED)
    return {
        "avg_score": round(sum(scores) / len(scores), 3),
        "best_vendor": best.vendor,
        "best_score": best.credibility_score,
        "worst_vendor": worst.vendor,
        "worst_score": worst.credibility_score,
        "total_claims": len(all_j),
        "total_supported": n_supported,
        "support_rate": round(n_supported / max(len(all_j), 1), 3),
    }


def finalize_market(result: MarketResult) -> MarketResult:
    for v in result.vendors:
        v.credibility_score = score_vendor(v.judgments)
    result.claim_inflation_index = claim_inflation_index(result.vendors)
    result.clusters = cluster_claims(result.vendors)
    result.benchmark = build_benchmark(result.vendors)
    return result
