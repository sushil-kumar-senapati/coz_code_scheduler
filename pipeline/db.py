import mysql.connector
from pipeline.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
import logging

log = logging.getLogger("pipeline.db")


def get_connection():
    return mysql.connector.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME,
        charset="utf8mb4", collation="utf8mb4_unicode_ci",
        autocommit=False,
    )


def fetch_one(conn, query, params=()):
    cur = conn.cursor(dictionary=True)
    cur.execute(query, params)
    row = cur.fetchone()
    cur.close()
    return row


def fetch_all(conn, query, params=()):
    cur = conn.cursor(dictionary=True)
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def execute(conn, query, params=()):
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    cur.close()


def execute_returning_uuid(conn, query, params=()):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT UUID() AS id")
    uid = cur.fetchone()["id"]
    cur.close()
    cur2 = conn.cursor()
    cur2.execute(query, (uid, *params))
    conn.commit()
    cur2.close()
    return uid


def insert_status_log(conn, raw_sub_id, user_id, old_status, new_status, reason=""):
    execute_returning_uuid(
        conn,
        """INSERT INTO submission_status_log
            (id, raw_submission_id, user_id, old_status, new_status, changed_by, change_reason)
           VALUES (%s, %s, %s, %s, %s, 'system', %s)""",
        (raw_sub_id, user_id, old_status, new_status, reason),
    )


def insert_notification(conn, user_id, raw_sub_id, cluster_id, ntype, title, message):
    execute_returning_uuid(
        conn,
        """INSERT INTO notifications
            (id, user_id, raw_submission_id, cluster_id, notification_type, title, message)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (user_id, raw_sub_id, cluster_id, ntype, title, message),
    )
