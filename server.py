"""
HTTP wrapper for Cloud Run Service deployment.
Runs the nightly schedule loop in a background thread and exposes:
  GET  /        — health check (Cloud Run startup/liveness probe)
  POST /run     — manually trigger the pipeline immediately
"""
import os
import threading
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

import schedule
from pipeline.config import SCHEDULER_TIME
from run_scheduler import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("server")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default per-request noise; pipeline logs its own output

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        if self.path == "/run":
            threading.Thread(target=run_pipeline, daemon=True).start()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"pipeline triggered")
        else:
            self.send_response(404)
            self.end_headers()


def schedule_loop():
    import time
    log.info(f"Schedule loop started — pipeline runs daily at {SCHEDULER_TIME}")
    schedule.every().day.at(SCHEDULER_TIME).do(run_pipeline)
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))

    # Run the nightly schedule in a background thread
    threading.Thread(target=schedule_loop, daemon=True).start()

    log.info(f"Scheduler service listening on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
