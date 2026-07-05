"""
Seed ALL 21 Odisha Lok Sabha constituencies with:
- Real MP details (2024 elections)
- MPLADS fund history (realistic data based on eSAKSHI patterns)
- Layer 4 data sources (Census 2011, UDISE+, IPHS, JJM, PMGSY, etc.)
- Budget tracker + scoring weights for each constituency
"""
import json
from pipeline.db import get_connection, execute, execute_returning_uuid, fetch_one

# ═══════════════════════════════════════════════════════════════════════════
# ALL 21 ODISHA LOK SABHA CONSTITUENCIES — 2024 ELECTION WINNERS
# ═══════════════════════════════════════════════════════════════════════════
CONSTITUENCIES = [
    # (constituency, mp_name, party, phone, pin_code, district, city)
    ("Bargarh", "Pradeep Purohit", "BJP", "9100000001", "768028", "Bargarh", "Bargarh"),
    ("Sundargarh", "Jual Oram", "BJP", "9100000002", "769001", "Sundargarh", "Sundargarh"),
    ("Sambalpur", "Dharmendra Pradhan", "BJP", "9100000003", "768001", "Sambalpur", "Sambalpur"),
    ("Keonjhar", "Ananta Nayak", "BJP", "9100000004", "758001", "Keonjhar", "Keonjhar"),
    ("Mayurbhanj", "Sudam Marandi", "BJP", "9100000005", "757001", "Mayurbhanj", "Baripada"),
    ("Balasore", "Pratap Chandra Sarangi", "BJP", "9100000006", "756001", "Balasore", "Balasore"),
    ("Bhadrak", "Avimanyu Sethi", "BJP", "9100000007", "756100", "Bhadrak", "Bhadrak"),
    ("Jajpur", "Rabindra Narayan Behera", "BJP", "9100000008", "755001", "Jajpur", "Jajpur"),
    ("Dhenkanal", "Rudra Narayan Pany", "BJP", "9100000009", "759001", "Dhenkanal", "Dhenkanal"),
    ("Bolangir", "Sangeeta Kumari Singh Deo", "BJP", "9100000010", "767001", "Bolangir", "Bolangir"),
    ("Kalahandi", "Malvika Devi", "BJP", "9100000011", "766001", "Kalahandi", "Bhawanipatna"),
    ("Nabarangpur", "Balabhadra Majhi", "BJP", "9100000012", "764059", "Nabarangpur", "Nabarangpur"),
    ("Kandhamal", "Sukanta Kumar Panigrahi", "BJP", "9100000013", "762001", "Kandhamal", "Phulbani"),
    ("Cuttack", "Bhartruhari Mahtab", "BJP", "9100000014", "753001", "Cuttack", "Cuttack"),
    ("Kendrapara", "Baijayant Jay Panda", "BJP", "9100000015", "754211", "Kendrapara", "Kendrapara"),
    ("Jagatsinghpur", "Bibhu Prasad Tarai", "BJP", "9000000001", "754103", "Jagatsinghpur", "Jagatsinghpur"),
    ("Puri", "Sambit Patra", "BJP", "9100000017", "752001", "Puri", "Puri"),
    ("Bhubaneswar", "Aparajita Sarangi", "BJP", "9100000018", "751001", "Khordha", "Bhubaneswar"),
    ("Aska", "Anita Subhadarshini", "BJP", "9100000019", "761101", "Ganjam", "Aska"),
    ("Berhampur", "Pradeep Kumar Panigrahy", "BJP", "9100000020", "760001", "Ganjam", "Berhampur"),
    ("Koraput", "Saptagiri Sankar Ulaka", "INC", "9100000021", "764020", "Koraput", "Koraput"),
]

# ═══════════════════════════════════════════════════════════════════════════
# DISTRICT-LEVEL DATA (Census 2011 + govt sources — all Odisha districts)
# ═══════════════════════════════════════════════════════════════════════════
DISTRICT_DATA = {
    # district: (population, sc_st_pct, literacy, female_lit, bpl_pct, households, gender_ratio,
    #            schools, student_teacher_ratio, toilet_pct, school_dist_km,
    #            phc_count, doctors, doctor_per_1000, phc_dist_km,
    #            tap_water_pct, road_connectivity_pct, electrification_pct, sanitation_pct)
    "Bargarh":       (1481255, 24.1, 75.6, 63.8, 39.2, 352000, 976, 1820, 25.1, 72.0, 2.5, 32, 96, 0.06, 7.8, 38.2, 72.5, 88.1, 71.0),
    "Sundargarh":    (2093437, 50.7, 73.2, 61.5, 35.8, 478000, 963, 2450, 28.3, 68.0, 3.1, 45, 135, 0.06, 8.5, 35.0, 68.0, 85.2, 65.0),
    "Sambalpur":     (1044410, 37.4, 76.9, 65.2, 32.5, 248000, 975, 1380, 23.5, 75.0, 2.2, 28, 112, 0.11, 6.5, 42.0, 76.0, 90.5, 74.0),
    "Jharsuguda":    (579505, 33.2, 78.4, 67.1, 28.0, 138000, 960, 680, 22.8, 78.0, 2.0, 14, 56, 0.10, 5.8, 48.0, 82.0, 93.0, 78.0),
    "Deogarh":       (312164, 39.5, 64.8, 51.2, 48.5, 72000, 986, 520, 32.5, 58.0, 4.2, 8, 18, 0.06, 12.0, 28.0, 62.0, 78.5, 55.0),
    "Keonjhar":      (1802777, 45.4, 69.0, 56.8, 42.1, 412000, 978, 2280, 30.2, 62.0, 3.5, 38, 95, 0.05, 9.2, 32.0, 65.0, 82.0, 60.0),
    "Mayurbhanj":    (2519738, 57.9, 63.2, 50.5, 52.5, 568000, 1005, 3450, 35.0, 55.0, 4.0, 52, 104, 0.04, 10.5, 25.0, 60.0, 76.0, 52.0),
    "Balasore":      (2320529, 22.5, 80.7, 71.2, 30.5, 528000, 957, 2850, 24.0, 76.0, 1.8, 48, 192, 0.08, 5.5, 45.0, 80.0, 92.5, 76.0),
    "Bhadrak":       (1506522, 22.8, 83.3, 74.5, 33.2, 345000, 981, 1680, 22.5, 80.0, 1.5, 32, 128, 0.08, 4.8, 48.0, 82.0, 93.0, 78.0),
    "Jajpur":        (1826275, 23.6, 80.1, 70.8, 35.8, 418000, 971, 2050, 23.8, 74.0, 1.9, 38, 114, 0.06, 5.8, 42.0, 78.0, 91.0, 72.0),
    "Dhenkanal":     (1192948, 24.0, 79.4, 69.5, 34.0, 276000, 947, 1520, 24.5, 72.0, 2.4, 25, 75, 0.06, 6.8, 40.0, 75.0, 89.0, 70.0),
    "Angul":         (1271703, 25.1, 78.3, 67.8, 31.0, 296000, 941, 1580, 25.0, 74.0, 2.3, 28, 98, 0.08, 6.2, 44.0, 78.0, 91.0, 73.0),
    "Bolangir":      (1648997, 25.2, 65.5, 52.1, 47.0, 368000, 980, 2180, 32.0, 58.0, 3.8, 32, 64, 0.04, 9.5, 28.0, 62.0, 80.0, 55.0),
    "Sonepur":       (542321, 27.8, 74.4, 62.5, 42.0, 126000, 966, 720, 28.0, 65.0, 3.0, 12, 36, 0.07, 7.5, 35.0, 70.0, 85.0, 62.0),
    "Kalahandi":     (1576869, 38.5, 60.2, 46.8, 55.0, 352000, 1003, 2250, 35.5, 52.0, 4.5, 30, 60, 0.04, 11.0, 22.0, 58.0, 75.0, 48.0),
    "Nuapada":       (610382, 40.2, 58.2, 43.5, 58.0, 138000, 1020, 880, 38.0, 48.0, 5.0, 12, 24, 0.04, 13.0, 18.0, 52.0, 70.0, 42.0),
    "Nabarangpur":   (1220946, 55.8, 48.2, 34.8, 62.0, 268000, 1018, 1850, 42.0, 42.0, 5.5, 22, 44, 0.04, 14.0, 15.0, 48.0, 68.0, 38.0),
    "Kandhamal":     (733110, 53.6, 64.1, 52.8, 52.0, 165000, 1003, 1120, 30.0, 55.0, 4.8, 15, 30, 0.04, 12.5, 22.0, 55.0, 72.0, 48.0),
    "Boudh":         (441162, 26.5, 72.5, 60.2, 44.0, 100000, 981, 650, 28.0, 62.0, 3.5, 10, 20, 0.05, 9.0, 30.0, 65.0, 82.0, 58.0),
    "Cuttack":       (2624470, 18.5, 84.2, 76.9, 26.8, 605200, 958, 2450, 22.2, 84.5, 1.6, 62, 340, 0.13, 5.2, 59.0, 84.0, 93.2, 82.0),
    "Kendrapara":    (1440361, 20.8, 85.5, 78.0, 30.0, 330000, 1006, 1620, 21.5, 82.0, 1.4, 35, 140, 0.10, 4.5, 52.0, 80.0, 92.0, 78.0),
    "Jagatsinghpur": (1136971, 21.8, 86.6, 79.4, 32.1, 275842, 977, 1245, 21.8, 82.2, 1.8, 38, 142, 0.12, 6.2, 55.0, 78.1, 91.2, 80.2),
    "Puri":          (1698730, 19.3, 85.4, 77.8, 35.2, 412340, 972, 1680, 22.9, 78.0, 2.1, 42, 168, 0.10, 7.5, 50.0, 75.0, 89.8, 77.3),
    "Khordha":       (2246341, 14.0, 87.5, 82.1, 18.0, 520000, 929, 1850, 20.5, 88.0, 1.2, 52, 420, 0.19, 3.5, 65.0, 88.0, 95.5, 88.0),
    "Nayagarh":      (963169, 17.2, 79.2, 68.5, 36.0, 222000, 918, 1180, 26.0, 70.0, 2.8, 20, 60, 0.06, 7.0, 38.0, 72.0, 88.0, 68.0),
    "Ganjam":        (3529031, 18.8, 71.1, 59.2, 38.5, 812000, 986, 4250, 27.0, 68.0, 2.5, 68, 204, 0.06, 6.8, 40.0, 74.0, 88.0, 68.0),
    "Gajapati":      (577817, 54.3, 54.3, 39.5, 58.0, 128000, 1042, 820, 35.0, 45.0, 5.2, 12, 24, 0.04, 14.0, 18.0, 50.0, 65.0, 40.0),
    "Koraput":       (1379647, 53.5, 49.2, 36.2, 60.0, 312000, 1031, 2050, 38.0, 45.0, 5.0, 28, 56, 0.04, 12.0, 18.0, 52.0, 70.0, 42.0),
    "Malkangiri":    (613192, 57.8, 49.5, 37.5, 65.0, 138000, 1020, 950, 42.0, 38.0, 6.0, 12, 24, 0.04, 15.0, 12.0, 45.0, 62.0, 35.0),
    "Rayagada":      (967911, 56.0, 50.9, 38.2, 58.0, 218000, 1048, 1380, 36.0, 42.0, 5.5, 18, 36, 0.04, 13.0, 15.0, 48.0, 68.0, 40.0),
}

# Constituency → Primary districts mapping
CONST_DISTRICTS = {
    "Bargarh": ["Bargarh", "Sambalpur"],
    "Sundargarh": ["Sundargarh"],
    "Sambalpur": ["Sambalpur", "Deogarh", "Jharsuguda"],
    "Keonjhar": ["Keonjhar"],
    "Mayurbhanj": ["Mayurbhanj"],
    "Balasore": ["Balasore"],
    "Bhadrak": ["Bhadrak"],
    "Jajpur": ["Jajpur"],
    "Dhenkanal": ["Dhenkanal", "Angul"],
    "Bolangir": ["Bolangir", "Sonepur"],
    "Kalahandi": ["Kalahandi", "Nuapada"],
    "Nabarangpur": ["Nabarangpur"],
    "Kandhamal": ["Kandhamal", "Boudh"],
    "Cuttack": ["Cuttack"],
    "Kendrapara": ["Kendrapara"],
    "Jagatsinghpur": ["Jagatsinghpur", "Puri"],
    "Puri": ["Puri", "Nayagarh"],
    "Bhubaneswar": ["Khordha"],
    "Aska": ["Ganjam", "Gajapati"],
    "Berhampur": ["Ganjam"],
    "Koraput": ["Koraput", "Malkangiri", "Rayagada"],
}

# MPLADS spending categories with realistic proportions
MPLADS_SPEND_PATTERNS = {
    "urban":  [("ROADS_PATHWAYS_BRIDGES", 0.38), ("DRINKING_WATER", 0.14), ("EDUCATION", 0.10), ("HEALTH", 0.10), ("SANITATION", 0.08), ("ELECTRICITY", 0.07), ("COMMUNITY_INFRASTRUCTURE", 0.06), ("SPORTS", 0.04), ("IRRIGATION", 0.03)],
    "semi":   [("ROADS_PATHWAYS_BRIDGES", 0.42), ("DRINKING_WATER", 0.15), ("EDUCATION", 0.08), ("HEALTH", 0.12), ("SANITATION", 0.06), ("ELECTRICITY", 0.06), ("COMMUNITY_INFRASTRUCTURE", 0.04), ("IRRIGATION", 0.04), ("DISASTER_RELIEF", 0.03)],
    "tribal": [("ROADS_PATHWAYS_BRIDGES", 0.35), ("DRINKING_WATER", 0.18), ("EDUCATION", 0.12), ("HEALTH", 0.14), ("SANITATION", 0.05), ("ELECTRICITY", 0.08), ("IRRIGATION", 0.05), ("DISASTER_RELIEF", 0.03)],
}

CONST_TYPE = {
    "Bargarh": "semi", "Sundargarh": "tribal", "Sambalpur": "semi", "Keonjhar": "tribal",
    "Mayurbhanj": "tribal", "Balasore": "semi", "Bhadrak": "semi", "Jajpur": "semi",
    "Dhenkanal": "semi", "Bolangir": "semi", "Kalahandi": "tribal", "Nabarangpur": "tribal",
    "Kandhamal": "tribal", "Cuttack": "urban", "Kendrapara": "semi", "Jagatsinghpur": "semi",
    "Puri": "semi", "Bhubaneswar": "urban", "Aska": "semi", "Berhampur": "urban", "Koraput": "tribal",
}

import bcrypt as _bcrypt
MP_PASSWORD_HASH = _bcrypt.hashpw(b"mp123456", _bcrypt.gensalt()).decode()


def seed_all():
    conn = get_connection()

    # ── 1. Seed MP users for all constituencies ─────────────────────────
    print("Seeding 21 MP users...")
    for const, mp_name, party, phone, pin, district, city in CONSTITUENCIES:
        existing = fetch_one(conn, "SELECT id FROM users WHERE phone = %s", (phone,))
        if existing:
            continue
        # Ensure PIN exists
        pin_exists = fetch_one(conn, "SELECT pin_code FROM pin_code_directory WHERE pin_code = %s", (pin,))
        if not pin_exists:
            execute(conn, """
                INSERT INTO pin_code_directory (pin_code, postal_name, locality, city, district, state, mp_constituency)
                VALUES (%s, %s, %s, %s, %s, 'Odisha', %s)
            """, (pin, city, city, city, district, const))
        execute_returning_uuid(conn, """
            INSERT INTO users (id, phone, password_hash, name, role, home_pin_code,
                home_postal_name, home_city, home_district, home_state, home_constituency)
            VALUES (%s, %s, %s, %s, 'mp', %s, %s, %s, %s, 'Odisha', %s)
        """, (phone, MP_PASSWORD_HASH, f"{mp_name} ({party})", pin, city, city, district, const))
    print(f"  ✓ 21 MP users seeded (all password: mp123456)")

    # ── 2. Budget tracker for all constituencies ─────────────────────────
    print("Seeding budget trackers...")
    for const, *_ in CONSTITUENCIES:
        existing = fetch_one(conn, "SELECT id FROM budget_tracker WHERE constituency = %s AND financial_year = '2026-27'", (const,))
        if not existing:
            execute_returning_uuid(conn, """
                INSERT INTO budget_tracker (id, constituency, financial_year, total_budget, remaining)
                VALUES (%s, %s, '2026-27', 50000000, 50000000)
            """, (const,))
    print(f"  ✓ 21 budget trackers seeded (₹5 Cr each)")

    # ── 3. Scoring weights for all constituencies ────────────────────────
    print("Seeding scoring weights...")
    for const, *_ in CONSTITUENCIES:
        existing = fetch_one(conn, "SELECT id FROM scoring_weights WHERE constituency = %s AND is_active = TRUE", (const,))
        if not existing:
            execute_returning_uuid(conn, """
                INSERT INTO scoring_weights (id, constituency, is_active) VALUES (%s, %s, TRUE)
            """, (const,))
    print(f"  ✓ 21 scoring weight configs seeded")

    # ── 4. Layer 4 data sources for ALL districts ────────────────────────
    print("Seeding Layer 4 data sources for all Odisha districts...")
    seeded_districts = set()
    for const, districts in CONST_DISTRICTS.items():
        for dist in districts:
            if dist in seeded_districts:
                continue
            seeded_districts.add(dist)
            d = DISTRICT_DATA.get(dist)
            if not d:
                continue
            pop, sc_st, lit, fem_lit, bpl, hh, gender, schools, str_, toilet_pct, sch_dist, phc, docs, doc_per_k, phc_dist, water, roads, elec, sanit = d

            sources = [
                ("census_village", dist, {"population": pop, "sc_st_pct": sc_st, "literacy_rate": lit, "female_literacy_rate": fem_lit, "households": hh, "gender_ratio": gender, "bpl_pct": bpl}, "2011"),
                ("secc_village", dist, {"bpl_pct": bpl, "landless_pct": round(bpl * 1.15, 1), "deprivation_score": round(bpl / 100, 2)}, "2011"),
                ("udise_school", dist, {"total_schools": schools, "enrollment": int(schools * 28), "teachers": int(schools * 28 / str_), "student_teacher_ratio": str_, "toilet_coverage_pct": toilet_pct, "school_distance_km": sch_dist}, "2023-24"),
                ("health_facility", dist, {"phc_count": phc, "chc_count": max(2, phc // 4), "total_doctors": docs, "doctor_per_1000": doc_per_k, "population_per_phc": int(pop / max(phc, 1)), "distance_to_phc_km": phc_dist}, "2024"),
                ("jjm_water", dist, {"total_hh": hh, "hh_with_tap": int(hh * water / 100), "tap_water_coverage_pct": water}, "2024-25"),
                ("pmgsy_road", dist, {"total_habitations": int(pop / 800), "connected_habitations": int(pop / 800 * roads / 100), "habitation_connectivity_pct": roads}, "2024"),
                ("saubhagya_electric", dist, {"total_hh": hh, "hh_electrified": int(hh * elec / 100), "electrification_pct": elec}, "2024"),
                ("sbm_sanitation", dist, {"total_hh": hh, "hh_with_toilet": int(hh * sanit / 100), "toilet_coverage_pct": sanit, "odf_status": "ODF" if sanit >= 70 else "Non-ODF"}, "2024"),
            ]
            for src_type, district, data, year in sources:
                existing = fetch_one(conn, "SELECT id FROM data_sources WHERE source_type = %s AND district = %s", (src_type, district))
                if not existing:
                    execute_returning_uuid(conn, """
                        INSERT INTO data_sources (id, source_type, state, district, data_json, data_year)
                        VALUES (%s, %s, 'Odisha', %s, %s, %s)
                    """, (src_type, district, json.dumps(data), year))
    print(f"  ✓ {len(seeded_districts)} districts × 8 sources = {len(seeded_districts) * 8} data rows seeded")

    # ── 5. MPLADS Fund History for all constituencies ────────────────────
    print("Seeding MPLADS fund history...")
    import random
    random.seed(42)  # Reproducible
    total_fund_rows = 0
    for const, *_ in CONSTITUENCIES:
        ctype = CONST_TYPE.get(const, "semi")
        pattern = MPLADS_SPEND_PATTERNS[ctype]
        for fy in ["2022-23", "2023-24", "2024-25"]:
            yearly_budget = random.randint(42000000, 50000000)  # ₹4.2-5 Cr
            for cat, pct in pattern:
                existing = fetch_one(conn, """
                    SELECT id FROM mplads_fund_history WHERE constituency = %s AND financial_year = %s AND category = %s
                """, (const, fy, cat))
                if existing:
                    continue
                sanctioned = int(yearly_budget * pct)
                spent = int(sanctioned * random.uniform(0.82, 0.95))
                works = max(1, int(sanctioned / random.randint(1500000, 4000000)))
                completed = max(0, works - random.randint(0, max(1, works // 3)))
                execute_returning_uuid(conn, """
                    INSERT INTO mplads_fund_history
                        (id, constituency, financial_year, category, amount_sanctioned, amount_spent,
                         works_count, works_completed, works_pending, works_in_progress)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (const, fy, cat, sanctioned, spent, works, completed,
                      max(0, works - completed - 1), min(1, works - completed)))
                total_fund_rows += 1
    print(f"  ✓ {total_fund_rows} fund history rows seeded (21 constituencies × 3 years)")

    conn.close()
    print(f"\n✅ All 21 Odisha constituencies seeded successfully!")
    print(f"   MPs: 21 (login with phone 9100000001-9100000021, password: mp123456)")
    print(f"   Jagatsinghpur MP: 9000000001 (unchanged)")
    print(f"   Data: {len(seeded_districts)} districts, {total_fund_rows} fund history rows")


if __name__ == "__main__":
    seed_all()
