"""
People's Priorities AI — Nightly Scheduler Service
===================================================
Runs Layers 2 → 3 → 4 → 5 pipeline every night at 23:30.
Can also be triggered manually via: python run_scheduler.py --now

Usage:
  python run_scheduler.py          # Start scheduler (runs at 23:30 daily)
  python run_scheduler.py --now    # Run pipeline immediately (for testing)
  python run_scheduler.py --seed   # Seed Layer 4 data only
"""

import sys
import time
import logging
import schedule
from datetime import datetime

from pipeline.config import SCHEDULER_TIME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("scheduler")


def run_pipeline():
    """Execute the full Layer 2 → 3 → 4 → 5 pipeline."""
    from pipeline.db import get_connection

    start = datetime.now()
    log.info("=" * 70)
    log.info(f"PIPELINE START — {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 70)

    conn = get_connection()

    try:
        # ── LAYER 2: Process raw submissions ─────────────────────────────
        from pipeline.layer2_processing import process_submissions
        l2_count = process_submissions(conn)

        # ── LAYER 3: Cluster & categorize ────────────────────────────────
        from pipeline.layer3_clustering import cluster_and_categorize
        l3_count = cluster_and_categorize(conn)

        # ── LAYER 4: Enrich with external data ──────────────────────────
        from pipeline.layer4_enrichment import enrich_clusters
        l4_count = enrich_clusters(conn)

        # ── LAYER 5: Score & rank ────────────────────────────────────────
        from pipeline.layer5_scoring import score_and_rank
        l5_count = score_and_rank(conn)

        elapsed = (datetime.now() - start).total_seconds()
        log.info("=" * 70)
        log.info(f"PIPELINE COMPLETE in {elapsed:.1f}s")
        log.info(f"  Layer 2: {l2_count} submissions processed")
        log.info(f"  Layer 3: {l3_count} submissions clustered")
        log.info(f"  Layer 4: {l4_count} clusters enriched")
        log.info(f"  Layer 5: {l5_count} clusters scored & ranked")
        log.info("=" * 70)

    except Exception as e:
        log.error(f"PIPELINE FAILED: {e}", exc_info=True)
    finally:
        conn.close()


def main():
    if "--seed" in sys.argv:
        log.info("Seeding Layer 4 data...")
        from seed_layer4_data import seed_all
        seed_all()
        return

    if "--now" in sys.argv:
        log.info("Running pipeline immediately (manual trigger)...")
        run_pipeline()
        return

    # Schedule mode
    log.info(f"Scheduler started. Pipeline will run daily at {SCHEDULER_TIME}")
    log.info("Press Ctrl+C to stop. Use --now to run immediately.")

    schedule.every().day.at(SCHEDULER_TIME).do(run_pipeline)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
