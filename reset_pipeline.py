"""Reset processed data so pipeline can re-run. For testing only."""
from pipeline.db import get_connection, execute

conn = get_connection()
execute(conn, "DELETE FROM cluster_scores")
execute(conn, "DELETE FROM cluster_submissions")
execute(conn, "DELETE FROM processing_queue")
execute(conn, "DELETE FROM processed_submissions")
execute(conn, "UPDATE demand_clusters SET status = 'forming', priority_score = NULL, `rank` = NULL, data_overlay = '{}'")
execute(conn, "DELETE FROM demand_clusters")
execute(conn, "UPDATE raw_submissions SET status = 'submitted'")
conn.close()
print("Reset complete — ready for re-run")
