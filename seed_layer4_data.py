"""
Seed realistic Layer 4 data sources for Khordha district (Bhubaneswar).
Run once to populate data_sources, infrastructure_norms, category_severity,
mplads_fund_history, and mplads_categories tables.
"""

import json
from pipeline.db import get_connection, execute, execute_returning_uuid, fetch_one


def seed_all():
    conn = get_connection()

    # ── MPLADS Categories ────────────────────────────────────────────────
    categories = [
        ("ROADS_PATHWAYS_BRIDGES", "Roads, Pathways & Bridges", "Construction and repair of roads, pathways, footbridges, and bridges"),
        ("EDUCATION", "Education", "School buildings, classrooms, libraries, laboratories, toilets in schools"),
        ("HEALTH", "Health & Family Welfare", "PHC/CHC construction, medical equipment, ambulances"),
        ("DRINKING_WATER", "Drinking Water", "Borewells, hand pumps, pipelines, water tanks"),
        ("SANITATION", "Sanitation", "Toilets, drainage, sewerage, waste management"),
        ("ELECTRICITY", "Electricity & Solar", "Street lights, solar panels, transformer installations"),
        ("IRRIGATION", "Irrigation & Flood Control", "Canals, check dams, embankments"),
        ("SPORTS", "Sports Infrastructure", "Playgrounds, stadiums, sports equipment"),
        ("COMMUNITY_INFRASTRUCTURE", "Community Infrastructure", "Community halls, bus stops, markets"),
        ("RAILWAYS", "Railway Related", "Level crossings, platform shelters, foot over bridges"),
        ("DISASTER_RELIEF", "Disaster Relief", "Cyclone shelters, relief materials"),
    ]
    for code, name, desc in categories:
        existing = fetch_one(conn, "SELECT id FROM mplads_categories WHERE code = %s", (code,))
        if not existing:
            execute_returning_uuid(conn, """
                INSERT INTO mplads_categories (id, code, name, description) VALUES (%s, %s, %s, %s)
            """, (code, name, desc))
    print(f"  MPLADS categories: {len(categories)} seeded")

    # ── Category Severity ────────────────────────────────────────────────
    severities = [
        ("DRINKING_WATER", 1.00, "CRITICAL", "Life-essential. JJM national mission target."),
        ("HEALTH", 0.95, "CRITICAL", "Life-critical. Doctor shortage acute in rural India."),
        ("SANITATION", 0.90, "CRITICAL", "Disease prevention. Swachh Bharat priority."),
        ("EDUCATION", 0.85, "CRITICAL", "Foundation for development. RTE norms."),
        ("ROADS_PATHWAYS_BRIDGES", 0.75, "HIGH", "Connectivity. Already gets 43% funds."),
        ("ELECTRICITY", 0.70, "HIGH", "Quality of life. Saubhagya target 100%."),
        ("IRRIGATION", 0.65, "HIGH", "Livelihood. Monsoon urgency."),
        ("DISASTER_RELIEF", 0.60, "MEDIUM", "Emergency response."),
        ("COMMUNITY_INFRASTRUCTURE", 0.50, "MEDIUM", "Community needs."),
        ("SPORTS", 0.40, "LOW", "Quality of life."),
        ("RAILWAYS", 0.35, "LOW", "Supplementary to Railway Ministry."),
    ]
    for cat, score, label, just in severities:
        existing = fetch_one(conn, "SELECT id FROM category_severity WHERE category = %s", (cat,))
        if not existing:
            execute_returning_uuid(conn, """
                INSERT INTO category_severity (id, category, severity_score, severity_label, justification)
                VALUES (%s, %s, %s, %s, %s)
            """, (cat, score, label, just))
    print(f"  Category severity: {len(severities)} seeded")

    # ── Infrastructure Norms ─────────────────────────────────────────────
    norms = [
        # Education norms (RTE)
        ("EDUCATION", "school_distance_km", "Distance to nearest school in km", 1.0, "km", "less_is_better", "RTE Act 2009", "all"),
        ("EDUCATION", "student_teacher_ratio", "Students per teacher", 30.0, "ratio", "less_is_better", "RTE Act 2009", "all"),
        ("EDUCATION", "toilet_coverage_pct", "Schools with functional toilets %", 100.0, "percentage", "more_is_better", "Swachh Vidyalaya", "all"),
        # Health norms (IPHS)
        ("HEALTH", "phc_per_population", "Population per PHC", 30000.0, "population_per_facility", "less_is_better", "IPHS 2022", "plain"),
        ("HEALTH", "doctor_per_1000", "Doctors per 1000 population", 1.0, "ratio", "more_is_better", "WHO Standard", "all"),
        ("HEALTH", "distance_to_phc_km", "Distance to nearest PHC in km", 3.0, "km", "less_is_better", "IPHS 2022", "all"),
        # Water norms (JJM)
        ("DRINKING_WATER", "tap_water_coverage_pct", "HH with tap water connection %", 100.0, "percentage", "more_is_better", "Jal Jeevan Mission", "all"),
        # Roads norms (PMGSY)
        ("ROADS_PATHWAYS_BRIDGES", "habitation_connectivity_pct", "Connected habitations %", 100.0, "percentage", "more_is_better", "PMGSY Guidelines", "all"),
        # Sanitation norms
        ("SANITATION", "toilet_coverage_pct", "HH with toilet %", 100.0, "percentage", "more_is_better", "Swachh Bharat Mission", "all"),
        # Electricity norms
        ("ELECTRICITY", "electrification_pct", "HH electrification %", 100.0, "percentage", "more_is_better", "Saubhagya Scheme", "all"),
    ]
    for cat, name, desc, val, unit, comp, src, area in norms:
        existing = fetch_one(conn, "SELECT id FROM infrastructure_norms WHERE category = %s AND norm_name = %s", (cat, name))
        if not existing:
            execute_returning_uuid(conn, """
                INSERT INTO infrastructure_norms (id, category, norm_name, norm_description, norm_value, norm_unit, comparison_type, source_name, area_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (cat, name, desc, val, unit, comp, src, area))
    print(f"  Infrastructure norms: {len(norms)} seeded")

    # ── Data Sources (Khordha district) ──────────────────────────────────
    sources = [
        # Census village data
        ("census_village", "Khordha", {"population": 218000, "sc_st_pct": 22.5, "literacy_rate": 78.3, "female_literacy_rate": 68.1, "households": 48500, "gender_ratio": 946}, "2011"),
        # SECC data
        ("secc_village", "Khordha", {"bpl_pct": 28.4, "landless_pct": 42.1, "deprivation_score": 0.38}, "2011"),
        # UDISE+ schools
        ("udise_school", "Khordha", {"total_schools": 87, "enrollment": 32400, "teachers": 1420, "student_teacher_ratio": 22.8, "schools_with_toilet": 71, "schools_without_toilet": 16, "toilet_coverage_pct": 81.6, "schools_with_electricity": 68, "schools_with_library": 42, "school_distance_km": 2.3}, "2023-24"),
        # Health facilities
        ("health_facility", "Khordha", {"phc_count": 12, "chc_count": 3, "district_hospital": 1, "total_doctors": 89, "total_beds": 420, "population_per_phc": 18167, "doctor_per_1000": 0.41, "distance_to_phc_km": 4.8}, "2024"),
        # JJM water
        ("jjm_water", "Khordha", {"total_hh": 48500, "hh_with_tap": 28900, "tap_water_coverage_pct": 59.6, "functional_tap_pct": 92.3, "water_quality_tested": True}, "2024-25"),
        # PMGSY roads
        ("pmgsy_road", "Khordha", {"total_habitations": 142, "connected_habitations": 118, "unconnected_habitations": 24, "habitation_connectivity_pct": 83.1, "total_road_length_km": 312.5, "road_condition_good_pct": 67.0}, "2024"),
        # Saubhagya electricity
        ("saubhagya_electric", "Khordha", {"total_hh": 48500, "hh_electrified": 45200, "electrification_pct": 93.2, "street_light_coverage_pct": 62.0}, "2024"),
        # SBM sanitation
        ("sbm_sanitation", "Khordha", {"total_hh": 48500, "hh_with_toilet": 41300, "toilet_coverage_pct": 85.2, "odf_status": "ODF", "drainage_coverage_pct": 48.0}, "2024"),
    ]
    for src_type, district, data, year in sources:
        existing = fetch_one(conn, "SELECT id FROM data_sources WHERE source_type = %s AND district = %s", (src_type, district))
        if not existing:
            execute_returning_uuid(conn, """
                INSERT INTO data_sources (id, source_type, state, district, data_json, data_year)
                VALUES (%s, %s, 'Odisha', %s, %s, %s)
            """, (src_type, district, json.dumps(data), year))
    print(f"  Data sources: {len(sources)} seeded for Khordha")

    # ── MPLADS Fund History ──────────────────────────────────────────────
    history = [
        ("Bhubaneswar", "2023-24", "ROADS_PATHWAYS_BRIDGES", 21500000, 19800000, 8, 7, 0, 1),
        ("Bhubaneswar", "2023-24", "EDUCATION", 4000000, 3600000, 3, 2, 0, 1),
        ("Bhubaneswar", "2023-24", "HEALTH", 4750000, 4200000, 2, 2, 0, 0),
        ("Bhubaneswar", "2023-24", "DRINKING_WATER", 5500000, 4800000, 4, 3, 0, 1),
        ("Bhubaneswar", "2023-24", "SANITATION", 3200000, 2900000, 2, 2, 0, 0),
        ("Bhubaneswar", "2023-24", "ELECTRICITY", 3800000, 3500000, 3, 3, 0, 0),
        ("Bhubaneswar", "2023-24", "SPORTS", 2500000, 2100000, 2, 1, 0, 1),
        ("Bhubaneswar", "2023-24", "COMMUNITY_INFRASTRUCTURE", 3000000, 2800000, 2, 2, 0, 0),
        ("Bhubaneswar", "2024-25", "ROADS_PATHWAYS_BRIDGES", 19000000, 17500000, 7, 6, 0, 1),
        ("Bhubaneswar", "2024-25", "EDUCATION", 5500000, 4800000, 4, 3, 0, 1),
        ("Bhubaneswar", "2024-25", "HEALTH", 6000000, 5200000, 3, 2, 0, 1),
        ("Bhubaneswar", "2024-25", "DRINKING_WATER", 7000000, 6100000, 5, 4, 0, 1),
        ("Bhubaneswar", "2024-25", "SANITATION", 4500000, 4000000, 3, 2, 0, 1),
        ("Bhubaneswar", "2024-25", "ELECTRICITY", 4000000, 3700000, 3, 3, 0, 0),
        ("Bhubaneswar", "2024-25", "COMMUNITY_INFRASTRUCTURE", 2500000, 2200000, 2, 2, 0, 0),
    ]
    for const, fy, cat, sanc, spent, works, comp, pend, prog in history:
        existing = fetch_one(conn, """
            SELECT id FROM mplads_fund_history WHERE constituency = %s AND financial_year = %s AND category = %s
        """, (const, fy, cat))
        if not existing:
            execute_returning_uuid(conn, """
                INSERT INTO mplads_fund_history
                    (id, constituency, financial_year, category, amount_sanctioned, amount_spent,
                     works_count, works_completed, works_pending, works_in_progress)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (const, fy, cat, sanc, spent, works, comp, pend, prog))
    print(f"  Fund history: {len(history)} rows seeded")

    # ── Scoring Weights (default) ────────────────────────────────────────
    existing = fetch_one(conn, "SELECT id FROM scoring_weights WHERE constituency = 'Bhubaneswar' AND is_active = TRUE")
    if not existing:
        execute_returning_uuid(conn, """
            INSERT INTO scoring_weights (id, constituency, is_active) VALUES (%s, 'Bhubaneswar', TRUE)
        """, ())
    print("  Scoring weights: defaults seeded")

    conn.close()
    print("\nAll seed data loaded successfully!")


if __name__ == "__main__":
    seed_all()
