"""
LAYER 4: Data Fusion & Enrichment
==================================
Pipeline: demand_clusters (categorized) → demand_clusters (enriched with data_overlay)

For each categorized cluster:
  1. Look up its category + district/PIN in data_sources table
  2. Fetch infrastructure norms for that category
  3. Calculate infrastructure gap score by comparing actual vs norm
  4. Fetch Census/SECC demographic data (SC/ST%, BPL%, literacy)
  5. Fetch MPLADS spending history for bias correction
  6. Package all into data_overlay JSON on the cluster

DATA SOURCES (pre-loaded in data_sources table):
  - census_village: population, sc_st_pct, literacy, female_literacy, households
  - secc_village: bpl_pct, deprivation indicators
  - udise_school: schools count, enrollment, teachers, toilets, electricity
  - health_facility: phc_count, chc_count, doctors, beds, distance_km
  - jjm_water: total_hh, hh_with_tap, coverage_pct
  - pmgsy_road: total_habitations, connected, unconnected, road_length_km
  - saubhagya_electric: total_hh, hh_electrified, coverage_pct
  - sbm_sanitation: total_hh, hh_with_toilet, odf_status, coverage_pct
"""

import json
import logging
from pipeline.db import fetch_all, fetch_one, execute

log = logging.getLogger("pipeline.layer4")


# ── Category → Data Source Mapping ──────────────────────────────────────────

CATEGORY_DATA_NEEDS = {
    "ROADS_PATHWAYS_BRIDGES": ["pmgsy_road", "census_village"],
    "EDUCATION":              ["udise_school", "census_village"],
    "HEALTH":                 ["health_facility", "census_village"],
    "DRINKING_WATER":         ["jjm_water", "census_village"],
    "SANITATION":             ["sbm_sanitation", "census_village"],
    "ELECTRICITY":            ["saubhagya_electric", "census_village"],
    "IRRIGATION":             ["census_village"],
    "SPORTS":                 ["census_village"],
    "COMMUNITY_INFRASTRUCTURE": ["census_village"],
    "RAILWAYS":               ["census_village"],
    "DISASTER_RELIEF":        ["census_village"],
}


def _get_source_data(conn, source_type: str, district: str) -> dict | None:
    """Fetch the best matching data_source row for a type+district. Falls back to state-level defaults."""
    row = fetch_one(conn, """
        SELECT data_json, data_year FROM data_sources
        WHERE source_type = %s AND district = %s
        ORDER BY fetched_at DESC LIMIT 1
    """, (source_type, district))
    if row and row["data_json"]:
        data = row["data_json"]
        if isinstance(data, str):
            data = json.loads(data)
        return data

    # Fallback: use national average estimates when no district data exists
    # These are approximate India-wide averages from Census 2011 / government reports
    NATIONAL_DEFAULTS = {
        "census_village": {"population": 150000, "sc_st_pct": 25.2, "literacy_rate": 74.0, "female_literacy_rate": 65.5, "bpl_pct": 25.0, "households": 33000},
        "secc_village": {"bpl_pct": 25.0, "landless_pct": 38.0, "deprivation_score": 0.35},
        "udise_school": {"total_schools": 60, "enrollment": 22000, "teachers": 900, "student_teacher_ratio": 24.5, "toilet_coverage_pct": 75.0, "school_distance_km": 2.8},
        "health_facility": {"phc_count": 8, "chc_count": 2, "total_doctors": 45, "doctor_per_1000": 0.35, "distance_to_phc_km": 5.5, "population_per_phc": 25000},
        "jjm_water": {"total_hh": 33000, "hh_with_tap": 16500, "tap_water_coverage_pct": 50.0},
        "pmgsy_road": {"total_habitations": 100, "connected_habitations": 75, "habitation_connectivity_pct": 75.0},
        "saubhagya_electric": {"total_hh": 33000, "hh_electrified": 29700, "electrification_pct": 90.0},
        "sbm_sanitation": {"total_hh": 33000, "hh_with_toilet": 26400, "toilet_coverage_pct": 80.0, "odf_status": "ODF"},
    }
    default = NATIONAL_DEFAULTS.get(source_type)
    if default:
        log.info(f"    Using national average for {source_type} (no data for {district})")
    return default


def _get_norms(conn, category: str) -> list[dict]:
    """Fetch all infrastructure norms for a category."""
    return fetch_all(conn, """
        SELECT norm_name, norm_value, norm_unit, comparison_type
        FROM infrastructure_norms
        WHERE category = %s AND is_active = TRUE
    """, (category,))


def _calculate_infra_gap(actual_data: dict, norms: list[dict], category: str) -> tuple[float, dict]:
    """
    Calculate infrastructure gap score by comparing actual data against norms.
    Returns (gap_score 0.0-1.0, details dict).

    gap = 0.0 means infrastructure is perfect (no gap)
    gap = 1.0 means critical gap (far from standard)
    """
    if not norms or not actual_data:
        return 0.5, {"note": "Insufficient data, using default gap"}

    gap_scores = []
    details = {}

    for norm in norms:
        norm_name = norm["norm_name"]
        norm_value = float(norm["norm_value"])
        comparison = norm["comparison_type"]
        actual_value = actual_data.get(norm_name)

        if actual_value is None:
            continue

        actual_value = float(actual_value)
        if comparison == "more_is_better":
            # e.g., coverage: 45% actual vs 100% norm → gap = 1 - 0.45 = 0.55
            if norm_value > 0:
                gap = max(0.0, min(1.0, 1.0 - (actual_value / norm_value)))
            else:
                gap = 0.0
        else:  # less_is_better
            # e.g., distance: 4.2km actual vs 1.0km norm → gap = min(4.2/5.0, 1.0) = 0.84
            if norm_value > 0:
                gap = max(0.0, min(1.0, actual_value / (norm_value * 5)))  # 5x norm = max gap
            else:
                gap = 0.0

        gap_scores.append(gap)
        details[norm_name] = {
            "actual": actual_value,
            "norm": norm_value,
            "gap": round(gap, 3),
            "unit": norm["norm_unit"],
        }

    if gap_scores:
        avg_gap = sum(gap_scores) / len(gap_scores)
    else:
        avg_gap = 0.5  # Default when no norms match

    return round(avg_gap, 4), details


def _get_demographics(conn, district: str) -> dict:
    """Fetch Census/SECC demographic data for vulnerability scoring."""
    census = _get_source_data(conn, "census_village", district)
    secc = _get_source_data(conn, "secc_village", district)

    demo = {
        "population": 0,
        "sc_st_pct": 0.0,
        "literacy_rate": 0.0,
        "female_literacy_rate": 0.0,
        "bpl_pct": 0.0,
        "households": 0,
    }

    if census:
        demo["population"] = census.get("population", 0)
        demo["sc_st_pct"] = census.get("sc_st_pct", 0.0)
        demo["literacy_rate"] = census.get("literacy_rate", 0.0)
        demo["female_literacy_rate"] = census.get("female_literacy_rate", 0.0)
        demo["households"] = census.get("households", 0)

    if secc:
        demo["bpl_pct"] = secc.get("bpl_pct", 0.0)

    return demo


def _get_fund_history(conn, constituency: str, category: str) -> dict:
    """Fetch MPLADS spending history for historical bias correction."""
    rows = fetch_all(conn, """
        SELECT category, SUM(amount_sanctioned) AS total
        FROM mplads_fund_history
        WHERE constituency = %s
        GROUP BY category
    """, (constituency,))

    total_all = sum(float(r["total"]) for r in rows) if rows else 0
    category_total = 0
    max_total = 0

    for r in rows:
        rt = float(r["total"])
        if r["category"] == category:
            category_total = rt
        max_total = max(max_total, rt)

    sector_pct = (category_total / total_all * 100) if total_all > 0 else 0
    max_pct = (max_total / total_all * 100) if total_all > 0 else 0

    return {
        "sector_spend_pct": round(sector_pct, 2),
        "max_sector_spend_pct": round(max_pct, 2),
        "sector_total": category_total,
        "all_sectors_total": total_all,
    }


# ── Main Layer 4 Processor ──────────────────────────────────────────────────

def enrich_clusters(conn) -> int:
    """
    Enrich all categorized (but not yet enriched) clusters with external data.
    Returns count of enriched clusters.
    """
    clusters = fetch_all(conn, """
        SELECT * FROM demand_clusters
        WHERE status = 'categorized' AND is_mplads_eligible = TRUE
    """)

    if not clusters:
        log.info("Layer 4: No categorized clusters to enrich")
        return 0

    log.info(f"Layer 4: Enriching {len(clusters)} clusters")
    enriched_count = 0

    for cluster in clusters:
        try:
            _enrich_one(conn, cluster)
            enriched_count += 1
        except Exception as e:
            log.error(f"  Error enriching cluster {cluster['id'][:8]}...: {e}")

    log.info(f"Layer 4: Enriched {enriched_count}/{len(clusters)} clusters")
    return enriched_count


def _enrich_one(conn, cluster: dict):
    """Enrich a single cluster with all required data for scoring."""
    cluster_id = cluster["id"]
    category = cluster["mplads_category_code"]
    district = cluster["district"]
    constituency = cluster["constituency"]

    log.info(f"  Enriching cluster {cluster_id[:8]}... (cat={category}, dist={district})")

    # 1. Fetch category-specific infrastructure data
    needed_sources = CATEGORY_DATA_NEEDS.get(category, ["census_village"])
    source_data = {}
    for src_type in needed_sources:
        data = _get_source_data(conn, src_type, district)
        if data:
            source_data[src_type] = data

    # 2. Fetch norms and calculate infrastructure gap
    norms = _get_norms(conn, category)
    sector_data = source_data.get(needed_sources[0], {}) if needed_sources else {}
    infra_gap_score, infra_gap_details = _calculate_infra_gap(sector_data, norms, category)

    # 3. Fetch demographics for vulnerability
    demographics = _get_demographics(conn, district)

    # 4. Fetch fund history for bias correction
    fund_history = _get_fund_history(conn, constituency, category)

    # 5. Get budget info for feasibility
    budget = fetch_one(conn, """
        SELECT remaining, total_budget FROM budget_tracker
        WHERE constituency = %s ORDER BY financial_year DESC LIMIT 1
    """, (constituency,))

    # 6. Package data_overlay
    data_overlay = {
        "demographics": demographics,
        "infrastructure": {
            "gap_score": infra_gap_score,
            "gap_details": infra_gap_details,
            "source_data": {k: v for k, v in source_data.items() if k != "census_village"},
        },
        "fund_history": fund_history,
        "budget": {
            "remaining": float(budget["remaining"]) if budget and budget["remaining"] else 50000000,
            "total": float(budget["total_budget"]) if budget and budget["total_budget"] else 50000000,
        },
        "enriched_sources": list(source_data.keys()),
    }

    # 7. Update cluster
    execute(conn, """
        UPDATE demand_clusters
        SET data_overlay = %s, status = 'enriched', updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (json.dumps(data_overlay), cluster_id))

    log.info(f"    Gap={infra_gap_score}, SC/ST={demographics['sc_st_pct']}%, BPL={demographics['bpl_pct']}%, "
             f"Sources={list(source_data.keys())}")
