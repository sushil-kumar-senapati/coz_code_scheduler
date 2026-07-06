"""
Integrated Layer 2 → 5 test — "think like real people".
=======================================================
Creates 5 realistic citizen scenarios in the Jagatsinghpur constituency
(2 submitted in native languages — Odia & Hindi — to exercise translation),
plus one real AUDIO submission, then runs the FULL pipeline (Layer 2 process →
Layer 3 cluster/categorize → Layer 4 enrich with real govt data → Layer 5 score
& rank) and prints the resulting leaderboard with the 7-factor breakdown and
anti-gaming multipliers.

Usage:
  python test_integrated_pipeline.py          # setup + run + report
  python test_integrated_pipeline.py --clean  # remove all test data only

All test data is tagged with phone prefix 999-0 and constituency 'Jagatsinghpur'
(district 'Jagatsinghpur', which has full seeded government data).
"""
import sys
import json
from pipeline.db import get_connection, execute, execute_returning_uuid, fetch_all, fetch_one

CONST = "Jagatsinghpur"
DIST = "Jagatsinghpur"
STATE = "Odisha"
TEST_PHONE_PREFIX = "9990"          # all test users
TEST_PW_HASH = "$2b$12$testtesttesttesttesttesttesttesttesttesttesttesttesttestte"  # dummy, login not used

# PINs used by the scenarios (all resolve to Jagatsinghpur district+constituency)
PINS = {
    "water": "754103",
    "school": "754110",
    "bridge": "754112",
    "spam": "754113",
    "gym": "754114",
    "audio": "754103",
}


def clean(conn):
    """Remove all test data in FK-safe order. All Jagatsinghpur clusters and all
    phone-prefix-999-0 users are test-created, so we scope deletes to both."""
    users = fetch_all(conn, "SELECT id FROM users WHERE phone LIKE %s", (TEST_PHONE_PREFIX + "%",))
    ids = [u["id"] for u in users]

    # 1) cluster-scoped children (all clusters in the test constituency)
    execute(conn, "DELETE cs FROM cluster_scores cs JOIN demand_clusters dc ON cs.cluster_id=dc.id WHERE dc.constituency=%s", (CONST,))
    execute(conn, "DELETE csub FROM cluster_submissions csub JOIN demand_clusters dc ON csub.cluster_id=dc.id WHERE dc.constituency=%s", (CONST,))

    if ids:
        ph = ",".join(["%s"] * len(ids))
        execute(conn, f"DELETE FROM notifications WHERE user_id IN ({ph})", tuple(ids))
        execute(conn, f"DELETE FROM submission_status_log WHERE user_id IN ({ph})", tuple(ids))
        execute(conn, f"DELETE FROM processing_queue WHERE raw_submission_id IN (SELECT id FROM raw_submissions WHERE user_id IN ({ph}))", tuple(ids))
        # processed_submissions reference demand_clusters via cluster_id → delete BEFORE clusters
        execute(conn, f"DELETE FROM processed_submissions WHERE user_id IN ({ph})", tuple(ids))
        execute(conn, f"DELETE FROM submission_media WHERE raw_submission_id IN (SELECT id FROM raw_submissions WHERE user_id IN ({ph}))", tuple(ids))

    # 2) now the clusters have no referencing rows
    execute(conn, "DELETE FROM demand_clusters WHERE constituency=%s", (CONST,))

    if ids:
        execute(conn, f"DELETE FROM raw_submissions WHERE user_id IN ({ph})", tuple(ids))
        execute(conn, f"DELETE FROM users WHERE id IN ({ph})", tuple(ids))
    print(f"  Cleaned {len(ids)} test users and their data.")


def ensure_pins(conn):
    for pin in set(PINS.values()):
        exists = fetch_one(conn, "SELECT pin_code FROM pin_code_directory WHERE pin_code=%s", (pin,))
        if not exists:
            execute(conn, """
                INSERT INTO pin_code_directory (pin_code, postal_name, locality, city, district, state, mp_constituency)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (pin, f"Jagatsinghpur Area {pin}", "Test Locality", "Jagatsinghpur", DIST, STATE, CONST))


def make_user(conn, phone, name, pin):
    uid = execute_returning_uuid(conn, """
        INSERT INTO users (id, phone, password_hash, name, role, home_pin_code,
                           home_district, home_state, home_constituency)
        VALUES (%s, %s, %s, %s, 'user', %s, %s, %s, %s)
    """, (phone, TEST_PW_HASH, name, pin, DIST, STATE, CONST))
    return uid


def make_submission(conn, uid, pin, input_type, text, lang, seq, media=None):
    tid = f"PP-TST-{seq:05d}"
    sub_id = execute_returning_uuid(conn, """
        INSERT INTO raw_submissions
            (id, tracking_id, user_id, submission_pin_code,
             sub_postal_name, sub_locality, sub_city, sub_district, sub_state, sub_constituency,
             input_type, raw_text, raw_language, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'submitted')
    """, (tid, uid, pin, f"Area {pin}", "Test Locality", "Jagatsinghpur", DIST, STATE, CONST,
          input_type, text, lang))
    if media:
        execute_returning_uuid(conn, """
            INSERT INTO submission_media (id, raw_submission_id, media_type, file_url, file_name, mime_type)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (sub_id, media["type"], media["url"], media["name"], media["mime"]))
    return sub_id


def setup(conn):
    print("Setting up 5 real-people scenarios in Jagatsinghpur...\n")
    ensure_pins(conn)
    seq = 1

    # ── Scenario A: Tribal water crisis (ODIA) — 8 citizens, 1 village ──
    odia_variants = [
        "ଆମ ଗାଁରେ ପାନୀୟ ଜଳ ନାହିଁ, ମହିଳାମାନେ ୪ କିଲୋମିଟର ଚାଲି ପାଣି ଆଣୁଛନ୍ତି।",
        "ଗାଁରେ କୌଣସି ନଳ ଜଳ ସଂଯୋଗ ନାହିଁ, ପାନୀୟ ଜଳର ଅଭାବ ରହିଛି।",
        "ପାଣି ପାଇଁ ମହିଳାମାନେ ପ୍ରତିଦିନ ବହୁ ଦୂର ଯିବାକୁ ପଡୁଛି, ଟ୍ୟୁବୱେଲ ଦରକାର।",
    ]
    for i in range(8):
        uid = make_user(conn, f"{TEST_PHONE_PREFIX}10{i:03d}", f"Water Citizen {i+1}", PINS["water"])
        make_submission(conn, uid, PINS["water"], "text", odia_variants[i % len(odia_variants)], "or", seq); seq += 1
    print("  A. Tribal Water (Odia)      : 8 citizens")

    # ── Scenario B: Broken primary school (HINDI) — 6 parents ──
    hindi_variants = [
        "हमारे गाँव के स्कूल में शौचालय काम नहीं करते और एक शिक्षक पर 85 बच्चे हैं।",
        "प्राथमिक विद्यालय में शौचालय टूटे हुए हैं और शिक्षकों की भारी कमी है।",
        "स्कूल में बच्चों के लिए शौचालय नहीं है, शिक्षक भी बहुत कम हैं।",
    ]
    for i in range(6):
        uid = make_user(conn, f"{TEST_PHONE_PREFIX}20{i:03d}", f"School Parent {i+1}", PINS["school"])
        make_submission(conn, uid, PINS["school"], "text", hindi_variants[i % len(hindi_variants)], "hi", seq); seq += 1
    print("  B. School Toilets (Hindi)   : 6 citizens")

    # ── Scenario C: Cut-off bridge / culvert collapse (English) — 3 farmers ──
    bridge_variants = [
        "The small culvert bridge collapsed in the monsoon and has cut off three farming hamlets completely.",
        "Our village bridge broke down during heavy rain, farmers cannot reach their fields or the market.",
        "The culvert on the village road collapsed, disconnecting our hamlet from the main road.",
    ]
    for i in range(3):
        uid = make_user(conn, f"{TEST_PHONE_PREFIX}30{i:03d}", f"Bridge Farmer {i+1}", PINS["bridge"])
        make_submission(conn, uid, PINS["bridge"], "text", bridge_variants[i], "en", seq); seq += 1
    print("  C. Bridge Collapse (English): 3 citizens")

    # ── Scenario D: Spammed market road (English) — 15 users, 60 submissions ──
    spots = [f"gate {n}" for n in range(1, 21)] + [f"shop block {c}" for c in "ABCDEFGHIJKLMNOPQRST"] + \
            [f"corner {n}" for n in range(1, 21)]
    s = 0
    for u in range(15):
        uid = make_user(conn, f"{TEST_PHONE_PREFIX}40{u:03d}", f"Market Shopkeeper {u+1}", PINS["spam"])
        for _ in range(4):  # 4 each = 60 total, <=5/day so not rate-limited
            text = f"Main Market Road is completely waterlogged with deep potholes near {spots[s % len(spots)]}, please repair urgently."
            make_submission(conn, uid, PINS["spam"], "text", text, "en", seq); seq += 1; s += 1
    print("  D. Spam Market Road (English): 15 citizens, 60 submissions (anti-gaming)")

    # ── Scenario E: Affluent open-air gym (English) — 12 residents ──
    gym_variants = [
        "We would like an open-air gym and reflexology walking track installed in our sector park.",
        "Please build an outdoor gym with exercise equipment in the neighbourhood park for residents.",
        "Request for an open gym and jogging track in our colony park for fitness activities.",
    ]
    for i in range(12):
        uid = make_user(conn, f"{TEST_PHONE_PREFIX}50{i:03d}", f"Sector Resident {i+1}", PINS["gym"])
        make_submission(conn, uid, PINS["gym"], "text", gym_variants[i % len(gym_variants)], "en", seq); seq += 1
    print("  E. Luxury Open Gym (English): 12 citizens")

    # ── Bonus: one real AUDIO submission (proves audio → text in-pipeline) ──
    audio = fetch_one(conn, "SELECT file_url, file_name, mime_type FROM submission_media WHERE media_type='audio' LIMIT 1")
    if audio:
        uid = make_user(conn, f"{TEST_PHONE_PREFIX}90000", "Audio Citizen", PINS["audio"])
        make_submission(conn, uid, PINS["audio"], "audio", None, "en", seq,
                        media={"type": "audio", "url": audio["file_url"], "name": audio["file_name"], "mime": audio["mime_type"]})
        seq += 1
        print("  +  Real audio submission     : 1 (Google ASR)")

    print(f"\n  Total: {seq-1} submissions created.\n")


def run_pipeline(conn):
    print("=" * 78)
    print("RUNNING PIPELINE  (Layer 2 → 3 → 4 → 5)")
    print("=" * 78)
    from pipeline.layer2_processing import process_submissions
    from pipeline.layer3_clustering import cluster_and_categorize
    from pipeline.layer4_enrichment import enrich_clusters
    from pipeline.layer5_scoring import score_and_rank
    l2 = process_submissions(conn)
    l3 = cluster_and_categorize(conn)
    l4 = enrich_clusters(conn)
    l5 = score_and_rank(conn)
    print(f"\n  Layer 2 processed : {l2}")
    print(f"  Layer 3 clustered : {l3}")
    print(f"  Layer 4 enriched  : {l4}")
    print(f"  Layer 5 scored    : {l5}\n")


def report(conn):
    print("=" * 78)
    print(f"LEADERBOARD — {CONST} constituency (scored on REAL seeded govt data)")
    print("=" * 78)
    rows = fetch_all(conn, """
        SELECT dc.`rank`, dc.mplads_category_code AS cat, dc.unique_users AS users,
               dc.submission_count AS subs, dc.priority_score AS score,
               dc.representative_text AS rep,
               cs.normalized_demand D, cs.normalized_severity S, cs.normalized_vulnerability V,
               cs.normalized_infra_gap I, cs.normalized_feasibility F, cs.normalized_recency R,
               cs.normalized_hist_bias H, cs.spam_decay_multiplier sd, cs.concentration_penalty cp
        FROM demand_clusters dc
        JOIN cluster_scores cs ON cs.cluster_id = dc.id
        WHERE dc.constituency = %s
        ORDER BY dc.`rank`
    """, (CONST,))

    for r in rows:
        print(f"\n#{r['rank']}  {r['cat']:24s}  SCORE {float(r['score']):.2f}/10   "
              f"({r['users']} users, {r['subs']} subs)")
        print(f"     \"{(r['rep'] or '')[:72]}\"")
        print(f"     D={float(r['D']):.2f} S={float(r['S']):.2f} V={float(r['V']):.2f} "
              f"I={float(r['I']):.2f} F={float(r['F']):.2f} R={float(r['R']):.2f} H={float(r['H']):.2f}  "
              f"| spam_decay={float(r['sd']):.2f} concentration={float(r['cp']):.2f}")

    # ── Assertions ──
    print("\n" + "=" * 78)
    print("VERIFYING PRIORITY LOGIC")
    print("=" * 78)
    by_cat = {r["cat"]: r for r in rows}
    checks = []

    def chk(name, cond):
        checks.append((name, cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    top = rows[0] if rows else None
    chk("Water crisis ranks #1 (top priority)", top is not None and top["cat"] == "DRINKING_WATER")
    water = next((r for r in rows if r["cat"] == "DRINKING_WATER"), None)
    chk("Native Odia was translated to English (water rep text is ASCII English)",
        water is not None and all(ord(c) < 128 for c in (water["rep"] or "x")))
    # anti-gaming: the 60-submission road cluster must be penalised
    spam = None
    for r in rows:
        if r["cat"] == "ROADS_PATHWAYS_BRIDGES" and r["subs"] >= 30:
            spam = r
    chk("Spam market road (60 subs) triggered anti-gaming (spam_decay<1 or concentration<1)",
        spam is not None and (float(spam["sd"]) < 1.0 or float(spam["cp"]) < 1.0))
    # recency fix: recent issues score HIGH (not ~0)
    chk("Recency fix works: fresh issues score high (all R > 0.8)",
        all(float(r["R"]) > 0.8 for r in rows))
    # spam road should rank below the genuine bridge despite far more submissions
    bridge = None
    for r in rows:
        if r["cat"] == "ROADS_PATHWAYS_BRIDGES" and r["subs"] <= 5:
            bridge = r
    if spam and bridge:
        chk("Anti-gaming works: 60-sub spam road ranks BELOW genuine 3-sub bridge",
            spam["rank"] > bridge["rank"])

    passed = sum(1 for _, c in checks if c)
    print(f"\n  {passed}/{len(checks)} checks passed.")
    return rows


def main():
    conn = get_connection()
    try:
        clean(conn)  # idempotent — start fresh
        if "--clean" in sys.argv:
            print("Clean-only mode. Done.")
            return
        setup(conn)
        run_pipeline(conn)
        report(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
