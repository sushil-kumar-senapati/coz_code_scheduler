"""
LAYER 3: Clustering, Deduplication & MPLADS Categorization
==========================================================
Pipeline: processed_submissions → demand_clusters + cluster_submissions

Steps:
  1. Fetch all non-spam processed submissions with status='processed'
  2. For each, compute text similarity against existing cluster representatives
  3. If similar enough (>0.55) → ADD to existing cluster
  4. If unique → CREATE new cluster
  5. Detect same-user duplicate: if user already in cluster → reject
  6. Categorize each cluster into MPLADS categories using keyword matching
  7. If not MPLADS-eligible → reject + notify users
"""

import re
import json
import logging
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from pipeline.db import (
    get_connection, fetch_all, fetch_one, execute, execute_returning_uuid,
    insert_status_log, insert_notification,
)

log = logging.getLogger("pipeline.layer3")

SIMILARITY_THRESHOLD = 0.40  # Lower for hackathon text diversity

# ── MPLADS Category Keyword Mapping ─────────────────────────────────────────
# Used for LLM-free classification. In production, replace with LLM call.

CATEGORY_KEYWORDS = {
    "ROADS_PATHWAYS_BRIDGES": [
        "road", "pothole", "bridge", "pathway", "footpath", "highway", "lane",
        "street", "flyover", "culvert", "tar", "asphalt", "pavement", "traffic",
        "accident", "speed breaker", "divider", "crossing", "junction",
    ],
    "EDUCATION": [
        "school", "classroom", "teacher", "student", "education", "college",
        "library", "laboratory", "playground", "toilet school", "scholarship",
        "enrollment", "midday meal", "anganwadi", "learning",
    ],
    "HEALTH": [
        "hospital", "health", "doctor", "phc", "chc", "medical", "clinic",
        "medicine", "ambulance", "dispensary", "nurse", "patient", "disease",
        "vaccine", "maternity", "health center", "asha worker",
    ],
    "DRINKING_WATER": [
        "water", "drinking water", "tap", "borewell", "tubewell", "pipeline",
        "water supply", "hand pump", "tanker", "well", "water tank",
        "jal jeevan", "contaminated water", "water scarcity",
    ],
    "SANITATION": [
        "toilet", "sanitation", "drainage", "sewer", "sewage", "gutter",
        "waste", "garbage", "dustbin", "open defecation", "odf", "cleanliness",
        "swachh", "drain", "stagnant water", "mosquito",
    ],
    "ELECTRICITY": [
        "electricity", "power", "electric", "light", "streetlight", "solar",
        "transformer", "pole", "wire", "voltage", "blackout", "power cut",
        "electrification", "led", "bulb", "lamp", "energy",
    ],
    "IRRIGATION": [
        "irrigation", "canal", "dam", "flood", "embankment", "river",
        "waterlogging", "monsoon", "crop", "farming", "agriculture",
    ],
    "SPORTS": [
        "sports", "stadium", "ground", "park", "recreation", "gym",
        "play area", "cricket", "football", "kabaddi",
    ],
    "COMMUNITY_INFRASTRUCTURE": [
        "community hall", "community center", "bus stop", "shelter",
        "public building", "panchayat", "market", "cremation", "burial",
    ],
    "RAILWAYS": [
        "railway", "rail", "level crossing", "station", "platform", "track",
        "train", "railway gate",
    ],
    "DISASTER_RELIEF": [
        "disaster", "cyclone", "earthquake", "relief", "emergency", "rescue",
    ],
}


def classify_category(text: str) -> tuple[str, float]:
    """Classify text into MPLADS category using keyword matching."""
    text_lower = text.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[cat] = score

    if not scores:
        return None, 0.0

    best_cat = max(scores, key=scores.get)
    confidence = min(scores[best_cat] / 3.0, 1.0)  # 3+ keyword matches = 1.0 confidence
    return best_cat, round(confidence, 2)


# ── Main Layer 3 Processor ──────────────────────────────────────────────────

def cluster_and_categorize(conn) -> int:
    """
    Cluster processed submissions and categorize into MPLADS sectors.
    Returns count of submissions clustered.
    """
    # Fetch unprocessed (processed but not yet clustered)
    new_subs = fetch_all(conn, """
        SELECT ps.*, rs.tracking_id
        FROM processed_submissions ps
        JOIN raw_submissions rs ON ps.raw_submission_id = rs.id
        WHERE ps.status = 'processed' AND ps.is_spam = FALSE
        ORDER BY ps.created_at ASC
    """)

    if not new_subs:
        log.info("Layer 3: No new processed submissions to cluster")
        return 0

    log.info(f"Layer 3: Clustering {len(new_subs)} processed submissions")

    # Fetch existing clusters with their representative texts
    existing_clusters = fetch_all(conn, """
        SELECT dc.id, dc.representative_text, dc.constituency, dc.unique_users,
               dc.submission_count, dc.pin_codes_covered
        FROM demand_clusters dc
        WHERE dc.status NOT IN ('closed')
    """)

    clustered_count = 0

    for sub in new_subs:
        try:
            _cluster_one(conn, sub, existing_clusters)
            clustered_count += 1
        except Exception as e:
            log.error(f"  Error clustering {sub.get('raw_submission_id')}: {e}")

    # After all clustering, categorize uncategorized clusters
    _categorize_clusters(conn)

    log.info(f"Layer 3: Clustered {clustered_count}/{len(new_subs)} submissions")
    return clustered_count


def _cluster_one(conn, sub: dict, existing_clusters: list):
    """Assign a single processed submission to a cluster (existing or new)."""
    sub_text = sub["translated_text_en"] or ""
    user_id = sub["user_id"]
    raw_sub_id = sub["raw_submission_id"]
    constituency = sub["constituency"] or ""
    pin_code = sub["pin_code"] or ""

    # Check if same user already has this text in a cluster (same-user duplicate)
    dup = fetch_one(conn, """
        SELECT csub.cluster_id FROM cluster_submissions csub
        JOIN processed_submissions ps ON csub.processed_submission_id = ps.id
        WHERE csub.user_id = %s AND ps.translated_text_en = %s
    """, (user_id, sub_text))

    if dup:
        log.info(f"  Same-user duplicate detected for user {user_id[:8]}... → rejecting")
        execute(conn, "UPDATE processed_submissions SET status = 'failed' WHERE id = %s", (sub["id"],))
        execute(conn, "UPDATE raw_submissions SET status = 'rejected' WHERE id = %s", (raw_sub_id,))
        insert_status_log(conn, raw_sub_id, user_id, "processed", "rejected",
                          "Duplicate: you already submitted this issue")
        insert_notification(conn, user_id, raw_sub_id, dup["cluster_id"],
                            "submission_status_update", "Duplicate Submission",
                            "This issue already exists in the system. Your earlier submission is being tracked.")
        return

    # Find best matching existing cluster
    best_cluster = None
    best_score = 0.0

    if existing_clusters and sub_text.strip():
        # Filter to same constituency
        same_const = [c for c in existing_clusters if c["constituency"] == constituency]
        if same_const:
            texts = [c["representative_text"] for c in same_const]
            texts.append(sub_text)

            vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
            try:
                tfidf_matrix = vectorizer.fit_transform(texts)
                similarities = cosine_similarity(tfidf_matrix[-1:], tfidf_matrix[:-1])[0]
                max_idx = np.argmax(similarities)
                best_score = float(similarities[max_idx])

                if best_score >= SIMILARITY_THRESHOLD:
                    best_cluster = same_const[max_idx]
            except Exception:
                pass  # If TF-IDF fails (e.g., empty texts), create new cluster

    if best_cluster:
        # ADD to existing cluster
        cluster_id = best_cluster["id"]
        log.info(f"  Matched to cluster {cluster_id[:8]}... (sim={best_score:.2f})")

        # Add to cluster_submissions
        execute_returning_uuid(conn, """
            INSERT INTO cluster_submissions (id, cluster_id, processed_submission_id, raw_submission_id, user_id, similarity_score)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (cluster_id, sub["id"], raw_sub_id, user_id, round(best_score, 3)))

        # Update cluster counts
        # Count unique users in this cluster
        unique_count = fetch_one(conn, """
            SELECT COUNT(DISTINCT user_id) AS cnt FROM cluster_submissions WHERE cluster_id = %s
        """, (cluster_id,))

        # Update PIN codes covered
        existing_pins = json.loads(best_cluster["pin_codes_covered"]) if best_cluster["pin_codes_covered"] else []
        if pin_code and pin_code not in existing_pins:
            existing_pins.append(pin_code)

        execute(conn, """
            UPDATE demand_clusters
            SET submission_count = submission_count + 1,
                unique_users = %s,
                pin_codes_covered = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (unique_count["cnt"], json.dumps(existing_pins), cluster_id))

        # Update processed_submission
        execute(conn, """
            UPDATE processed_submissions SET cluster_id = %s, clustered_at = CURRENT_TIMESTAMP, status = 'clustered'
            WHERE id = %s
        """, (cluster_id, sub["id"]))

    else:
        # CREATE new cluster
        cluster_id = execute_returning_uuid(conn, """
            INSERT INTO demand_clusters
                (id, constituency, district, state, pin_codes_covered,
                 representative_text, submission_count, unique_users, status)
            VALUES (%s, %s, %s, %s, %s, %s, 1, 1, 'forming')
        """, (
            constituency, sub["district"], sub["state"],
            json.dumps([pin_code] if pin_code else []),
            sub_text,
        ))

        log.info(f"  Created new cluster {cluster_id[:8]}...")

        # Add to cluster_submissions
        execute_returning_uuid(conn, """
            INSERT INTO cluster_submissions (id, cluster_id, processed_submission_id, raw_submission_id, user_id, similarity_score, is_representative)
            VALUES (%s, %s, %s, %s, %s, 1.000, TRUE)
        """, (cluster_id, sub["id"], raw_sub_id, user_id))

        # Update processed_submission
        execute(conn, """
            UPDATE processed_submissions SET cluster_id = %s, clustered_at = CURRENT_TIMESTAMP, status = 'clustered'
            WHERE id = %s
        """, (cluster_id, sub["id"]))

        # Add to our in-memory list for subsequent submissions in this batch
        existing_clusters.append({
            "id": cluster_id,
            "representative_text": sub_text,
            "constituency": constituency,
            "unique_users": 1,
            "submission_count": 1,
            "pin_codes_covered": json.dumps([pin_code] if pin_code else []),
        })

    # Update raw submission status
    execute(conn, "UPDATE raw_submissions SET status = 'clustered' WHERE id = %s", (raw_sub_id,))
    insert_status_log(conn, raw_sub_id, user_id, "processed", "clustered", "Grouped with similar issues")


def _categorize_clusters(conn):
    """Categorize all uncategorized clusters into MPLADS sectors."""
    uncategorized = fetch_all(conn, """
        SELECT * FROM demand_clusters
        WHERE mplads_category_code IS NULL AND status IN ('forming', 'categorized')
    """)

    if not uncategorized:
        return

    log.info(f"Layer 3: Categorizing {len(uncategorized)} clusters")

    for cluster in uncategorized:
        text = cluster["representative_text"] or ""
        category, confidence = classify_category(text)

        if category:
            # Check if this category exists in mplads_categories
            cat_row = fetch_one(conn, "SELECT id FROM mplads_categories WHERE code = %s", (category,))
            is_eligible = cat_row is not None

            execute(conn, """
                UPDATE demand_clusters
                SET mplads_category_code = %s, is_mplads_eligible = %s,
                    category_confidence = %s, status = 'categorized',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (category, is_eligible, confidence, cluster["id"]))

            log.info(f"  Cluster {cluster['id'][:8]}... → {category} (conf={confidence}, eligible={is_eligible})")

            if not is_eligible:
                # Notify all users in this cluster
                users_in_cluster = fetch_all(conn, """
                    SELECT DISTINCT csub.user_id, rs.tracking_id
                    FROM cluster_submissions csub
                    JOIN raw_submissions rs ON csub.raw_submission_id = rs.id
                    WHERE csub.cluster_id = %s
                """, (cluster["id"],))

                for u in users_in_cluster:
                    insert_notification(conn, u["user_id"], None, cluster["id"],
                                        "cluster_rejected",
                                        "Issue Not Under MPLADS",
                                        f"Your issue ({u['tracking_id']}) was categorized as '{category}' which is not eligible under MPLADS scheme. You can submit other MPLADS-related issues.")

        else:
            # Cannot classify from text — assign COMMUNITY_INFRASTRUCTURE as default
            # and mark for manual review. This ensures pipeline continues.
            default_cat = "COMMUNITY_INFRASTRUCTURE"
            log.info(f"  Cluster {cluster['id'][:8]}... → could not classify, defaulting to {default_cat} (needs review)")
            execute(conn, """
                UPDATE demand_clusters
                SET mplads_category_code = %s, is_mplads_eligible = TRUE,
                    category_confidence = 0.10, status = 'categorized',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (default_cat, cluster["id"]))
