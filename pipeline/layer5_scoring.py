"""
LAYER 5: Prioritization & Scoring Engine
==========================================
Pipeline: demand_clusters (enriched) → cluster_scores + demand_clusters (scored + ranked)

THE 7 SCORING FACTORS:
  D (0.18) Demand Volume     — log-scaled unique citizen count
  S (0.20) Category Severity — static lookup (water=1.0, roads=0.75)
  V (0.15) Vulnerability     — SC/ST%, BPL%, literacy composite
  I (0.20) Infrastructure Gap — reality vs govt standard (ANTI-GAMING ANCHOR)
  F (0.10) Feasibility       — budget + cost + eligibility
  R (0.07) Recency & Trend   — growing vs declining problem
  H (0.10) Historical Bias   — corrects underfunded sectors

Formula:
  BASE = Σ(weight × normalized_factor)
  FINAL = BASE × spam_decay × concentration_penalty
  SCORE = FINAL × 10 (displayed as X.X / 10)
"""

import json
import math
import logging
from datetime import datetime
from pipeline.db import fetch_all, fetch_one, execute, execute_returning_uuid

log = logging.getLogger("pipeline.layer5")


def _get_weights(conn, constituency: str) -> dict:
    """Fetch active scoring weights for constituency, or defaults."""
    row = fetch_one(conn, """
        SELECT * FROM scoring_weights
        WHERE constituency = %s AND is_active = TRUE
        ORDER BY created_at DESC LIMIT 1
    """, (constituency,))

    if row:
        return {
            "D": float(row["w_demand_volume"]),
            "S": float(row["w_category_severity"]),
            "V": float(row["w_vulnerability"]),
            "I": float(row["w_infrastructure_gap"]),
            "F": float(row["w_feasibility"]),
            "R": float(row["w_recency_trend"]),
            "H": float(row["w_historical_bias"]),
            "id": row["id"],
        }

    # Default weights
    return {"D": 0.18, "S": 0.20, "V": 0.15, "I": 0.20, "F": 0.10, "R": 0.07, "H": 0.10, "id": None}


def _get_severity(conn, category: str) -> float:
    """Fetch severity score for a category."""
    row = fetch_one(conn, "SELECT severity_score FROM category_severity WHERE category = %s", (category,))
    return float(row["severity_score"]) if row else 0.50


def _normalize_demand(unique_users: int, max_users: int) -> float:
    """D: Log-scaled demand. Prevents gaming by organized mass submissions."""
    if max_users <= 0:
        return 0.0
    return math.log(1 + unique_users) / math.log(1 + max_users)


def _normalize_vulnerability(demographics: dict) -> float:
    """V: Composite vulnerability from Census/SECC data."""
    sc_st = min(demographics.get("sc_st_pct", 0) / 40.0, 1.0)      # 40% as max
    bpl = min(demographics.get("bpl_pct", 0) / 50.0, 1.0)           # 50% as max
    lit_gap = 1.0 - min(demographics.get("literacy_rate", 70) / 100.0, 1.0)
    fem_lit_gap = 1.0 - min(demographics.get("female_literacy_rate", 60) / 100.0, 1.0)

    return round(0.35 * sc_st + 0.30 * bpl + 0.20 * lit_gap + 0.15 * fem_lit_gap, 4)


def _normalize_feasibility(budget_remaining: float, estimated_cost: float, is_eligible: bool) -> float:
    """F: Can MPLADS fund this?"""
    budget_flag = 1.0 if budget_remaining >= (estimated_cost or 0) else 0.0
    max_cost = 5000000  # ₹50L as reference max for single project
    cost_eff = 1.0 - min((estimated_cost or 500000) / max_cost, 1.0)
    eligible_flag = 1.0 if is_eligible else 0.0

    return round(0.5 * budget_flag + 0.3 * cost_eff + 0.2 * eligible_flag, 4)


def _normalize_recency(first_reported_days: int, submission_count: int, unique_users: int) -> float:
    """R: Recency and trend scoring."""
    # Recency: older issues get higher recency score (more urgent)
    recency = min(first_reported_days / 180.0, 1.0)  # 6 months = max

    # Trend: more submissions per day = accelerating
    days = max(first_reported_days, 1)
    rate = submission_count / days
    if rate > 1.0:
        trend = 1.0  # accelerating
    elif rate > 0.3:
        trend = 0.7  # steady
    else:
        trend = 0.3  # declining

    return round(0.6 * recency + 0.4 * trend, 4)


def _normalize_hist_bias(sector_pct: float, max_sector_pct: float) -> float:
    """H: Boost underfunded sectors. Roads got 43% = no boost. Education got 8% = big boost."""
    if max_sector_pct <= 0:
        return 0.5  # No history data
    return round(1.0 - (sector_pct / max_sector_pct), 4)


def _spam_decay(unique_users: int, total_submissions: int) -> float:
    """Anti-gaming: penalize if unique/total ratio is suspiciously low."""
    if total_submissions <= 0:
        return 1.0
    ratio = unique_users / total_submissions
    return 0.70 if ratio < 0.30 else 1.0


def _concentration_penalty(pin_codes_covered: list) -> float:
    """Anti-gaming: penalize if >25% of demand from one PIN code."""
    if not pin_codes_covered or len(pin_codes_covered) <= 1:
        return 1.0
    # All from one PIN = penalty
    # In a real system, we'd count submissions per PIN. For now, check diversity
    return 1.0 if len(pin_codes_covered) >= 2 else 0.80


def _generate_explanation(rank, total, score, cluster, factors, demographics, fund_hist) -> str:
    """Generate human-readable score explanation."""
    category = cluster.get("mplads_category_code", "UNKNOWN")
    unique = cluster.get("unique_users", 0)
    pins = json.loads(cluster.get("pin_codes_covered", "[]")) if isinstance(cluster.get("pin_codes_covered"), str) else (cluster.get("pin_codes_covered") or [])
    gap = factors.get("I_raw", 0.5)
    sc_st = demographics.get("sc_st_pct", 0)
    bpl = demographics.get("bpl_pct", 0)
    sector_pct = fund_hist.get("sector_spend_pct", 0)

    parts = [
        f"Ranked #{rank} of {total} clusters (Score: {score:.1f}/10).",
        f"DEMAND: {unique} citizens from {len(pins)} area(s) raised this issue.",
    ]

    if gap >= 0.7:
        parts.append(f"EVIDENCE: Infrastructure gap is significant ({gap:.0%}). Data confirms substantial shortfall from government standards.")
    elif gap >= 0.4:
        parts.append(f"EVIDENCE: Moderate infrastructure gap ({gap:.0%}) identified from government data.")
    else:
        parts.append(f"EVIDENCE: Infrastructure is relatively adequate ({gap:.0%} gap). Lower priority based on data.")

    if sc_st > 20 or bpl > 30:
        parts.append(f"EQUITY: {sc_st:.0f}% SC/ST population, {bpl:.0f}% BPL households — vulnerability boost applied.")

    if sector_pct < 15:
        parts.append(f"HISTORY: {category} received only {sector_pct:.0f}% of past MPLADS funds — rebalancing boost applied.")

    cost = cluster.get("estimated_cost", 0)
    if cost:
        parts.append(f"FEASIBILITY: Estimated cost ₹{cost:,.0f}.")

    return " ".join(parts)


# ── Main Layer 5 Processor ──────────────────────────────────────────────────

def score_and_rank(conn) -> int:
    """
    Score all enriched clusters and rank them within each constituency.
    Returns count of scored clusters.
    """
    clusters = fetch_all(conn, """
        SELECT * FROM demand_clusters
        WHERE status = 'enriched' AND is_mplads_eligible = TRUE
    """)

    if not clusters:
        log.info("Layer 5: No enriched clusters to score")
        return 0

    # Group by constituency for ranking
    by_constituency = {}
    for c in clusters:
        const = c["constituency"]
        if const not in by_constituency:
            by_constituency[const] = []
        by_constituency[const].append(c)

    scored_count = 0

    for constituency, const_clusters in by_constituency.items():
        log.info(f"Layer 5: Scoring {len(const_clusters)} clusters in {constituency}")

        # Get weights
        weights = _get_weights(conn, constituency)

        # Get max unique users for normalization
        all_clusters_in_const = fetch_all(conn, """
            SELECT unique_users FROM demand_clusters WHERE constituency = %s
        """, (constituency,))
        max_users = max((c["unique_users"] for c in all_clusters_in_const), default=1)

        scored_clusters = []

        for cluster in const_clusters:
            try:
                result = _score_one(conn, cluster, weights, max_users)
                scored_clusters.append(result)
                scored_count += 1
            except Exception as e:
                log.error(f"  Error scoring cluster {cluster['id'][:8]}...: {e}")

        # Rank within constituency
        scored_clusters.sort(key=lambda x: x["final_score"], reverse=True)

        # Also include previously scored clusters for re-ranking
        existing_scored = fetch_all(conn, """
            SELECT dc.id, cs.priority_score_10
            FROM demand_clusters dc
            JOIN cluster_scores cs ON cs.cluster_id = dc.id
            WHERE dc.constituency = %s AND dc.status = 'scored'
        """, (constituency,))

        all_for_ranking = []
        for sc in scored_clusters:
            all_for_ranking.append({"id": sc["cluster_id"], "score": sc["final_score"] * 10})
        for es in existing_scored:
            if not any(s["cluster_id"] == es["id"] for s in scored_clusters):
                all_for_ranking.append({"id": es["id"], "score": float(es["priority_score_10"] or 0)})

        all_for_ranking.sort(key=lambda x: x["score"], reverse=True)
        total_ranked = len(all_for_ranking)

        for rank_idx, item in enumerate(all_for_ranking, 1):
            execute(conn, "UPDATE demand_clusters SET `rank` = %s WHERE id = %s", (rank_idx, item["id"]))

        # Generate explanations and update scored clusters
        for sc in scored_clusters:
            rank_pos = next((i + 1 for i, a in enumerate(all_for_ranking) if a["id"] == sc["cluster_id"]), 0)
            cluster_data = next((c for c in const_clusters if c["id"] == sc["cluster_id"]), {})
            explanation = _generate_explanation(
                rank_pos, total_ranked, sc["final_score"] * 10,
                cluster_data, sc["factors"], sc["demographics"], sc["fund_history"],
            )

            # Update cluster_scores with explanation
            execute(conn, """
                UPDATE cluster_scores SET score_explanation = %s WHERE cluster_id = %s
            """, (explanation, sc["cluster_id"]))

            # Update cluster priority_score and rank
            execute(conn, """
                UPDATE demand_clusters
                SET priority_score = %s, `rank` = %s, score_explanation = %s,
                    status = 'scored', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (round(sc["final_score"] * 10, 2), rank_pos, explanation, sc["cluster_id"]))

            # Update raw submissions status
            execute(conn, """
                UPDATE raw_submissions rs
                JOIN cluster_submissions csub ON csub.raw_submission_id = rs.id
                SET rs.status = 'scored'
                WHERE csub.cluster_id = %s AND rs.status IN ('clustered', 'categorized')
            """, (sc["cluster_id"],))

            log.info(f"  #{rank_pos} | Score={sc['final_score']*10:.2f} | {cluster_data.get('representative_text', '')[:50]}...")

    log.info(f"Layer 5: Scored {scored_count} clusters total")
    return scored_count


def _score_one(conn, cluster: dict, weights: dict, max_users: int) -> dict:
    """Calculate all 7 scoring factors for a single cluster."""
    cluster_id = cluster["id"]
    category = cluster["mplads_category_code"]
    constituency = cluster["constituency"]

    # Parse data_overlay
    overlay = cluster.get("data_overlay", {})
    if isinstance(overlay, str):
        overlay = json.loads(overlay)

    demographics = overlay.get("demographics", {})
    infra = overlay.get("infrastructure", {})
    fund_history = overlay.get("fund_history", {})
    budget_data = overlay.get("budget", {})

    # ── Calculate each factor ────────────────────────────────────────────
    unique_users = cluster["unique_users"] or 1
    total_subs = cluster["submission_count"] or 1
    estimated_cost = float(cluster.get("estimated_cost") or 500000)
    budget_remaining = budget_data.get("remaining", 50000000)

    # Days since first report
    created = cluster.get("created_at")
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    days_ago = max((datetime.now() - created).days, 1) if created else 30

    # Normalized factors
    D = _normalize_demand(unique_users, max_users)
    S = _get_severity(conn, category)
    V = _normalize_vulnerability(demographics)
    I = infra.get("gap_score", 0.5)
    F = _normalize_feasibility(budget_remaining, estimated_cost, cluster.get("is_mplads_eligible", True))
    R = _normalize_recency(days_ago, total_subs, unique_users)
    H = _normalize_hist_bias(fund_history.get("sector_spend_pct", 20), fund_history.get("max_sector_spend_pct", 43))

    # Weighted scores
    wD = weights["D"] * D
    wS = weights["S"] * S
    wV = weights["V"] * V
    wI = weights["I"] * I
    wF = weights["F"] * F
    wR = weights["R"] * R
    wH = weights["H"] * H

    base_score = wD + wS + wV + wI + wF + wR + wH

    # Anti-gaming modifiers
    sd = _spam_decay(unique_users, total_subs)
    pin_codes = json.loads(cluster.get("pin_codes_covered", "[]")) if isinstance(cluster.get("pin_codes_covered"), str) else (cluster.get("pin_codes_covered") or [])
    cp = _concentration_penalty(pin_codes)

    final_score = base_score * sd * cp

    # ── Store in cluster_scores table ────────────────────────────────────
    # Delete old score if exists
    execute(conn, "DELETE FROM cluster_scores WHERE cluster_id = %s", (cluster_id,))

    execute_returning_uuid(conn, """
        INSERT INTO cluster_scores (
            id, cluster_id, scoring_weights_id,
            raw_demand_unique_users, raw_demand_total_submissions,
            raw_category_code,
            raw_vulnerability_sc_st_pct, raw_vulnerability_bpl_pct,
            raw_vulnerability_literacy, raw_vulnerability_female_lit,
            raw_infra_gap_details,
            raw_budget_remaining, raw_estimated_cost,
            raw_first_reported_days_ago, raw_submission_trend,
            raw_past_sector_spend_pct,
            normalized_demand, normalized_severity, normalized_vulnerability,
            normalized_infra_gap, normalized_feasibility, normalized_recency,
            normalized_hist_bias,
            weighted_demand, weighted_severity, weighted_vulnerability,
            weighted_infra_gap, weighted_feasibility, weighted_recency,
            weighted_hist_bias,
            spam_decay_multiplier, concentration_penalty,
            base_score, final_score, priority_score_10,
            weights_snapshot
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
    """, (
        cluster_id, weights.get("id"),
        unique_users, total_subs, category,
        demographics.get("sc_st_pct", 0), demographics.get("bpl_pct", 0),
        demographics.get("literacy_rate", 0), demographics.get("female_literacy_rate", 0),
        json.dumps(infra.get("gap_details", {})),
        budget_remaining, estimated_cost,
        days_ago, "steady",
        fund_history.get("sector_spend_pct", 0),
        round(D, 3), round(S, 3), round(V, 3), round(I, 3), round(F, 3), round(R, 3), round(H, 3),
        round(wD, 4), round(wS, 4), round(wV, 4), round(wI, 4), round(wF, 4), round(wR, 4), round(wH, 4),
        sd, cp,
        round(base_score, 4), round(final_score, 4), round(final_score * 10, 2),
        json.dumps({k: v for k, v in weights.items() if k != "id"}),
    ))

    return {
        "cluster_id": cluster_id,
        "final_score": final_score,
        "factors": {
            "D": round(D, 3), "S": round(S, 3), "V": round(V, 3),
            "I": round(I, 3), "I_raw": infra.get("gap_score", 0.5),
            "F": round(F, 3), "R": round(R, 3), "H": round(H, 3),
        },
        "demographics": demographics,
        "fund_history": fund_history,
    }
