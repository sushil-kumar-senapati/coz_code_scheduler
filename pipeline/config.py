import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "people's_priority")

SCHEDULER_TIME = os.getenv("SCHEDULER_TIME", "23:30")

# ── Layer 2 media processing config ─────────────────────────────────────────
# Where the backend saved citizen audio/image files. Auto-resolve to the
# sibling backend repo's uploads/ folder if not set explicitly.
_DEFAULT_UPLOAD_BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "coz_code_backend", "uploads")
)
UPLOAD_BASE_DIR = os.getenv("UPLOAD_BASE_DIR") or _DEFAULT_UPLOAD_BASE

# ffmpeg / ffprobe for pydub audio conversion (blank = rely on PATH)
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "").strip()
FFPROBE_PATH = os.getenv("FFPROBE_PATH", "").strip()

# Google Cloud Vision API key (OCR). Blank = OCR disabled with clear warning.
GOOGLE_VISION_API_KEY = os.getenv("GOOGLE_VISION_API_KEY", "").strip()

# ── Google services mode: 'dev' (free/offline) or 'cloud' (official GCP) ─────
GOOGLE_MODE = os.getenv("GOOGLE_MODE", "dev").strip().lower()

# GCP settings (only used when GOOGLE_MODE=cloud)
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
GCP_PROJECT = os.getenv("GCP_PROJECT", "").strip()
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1").strip()

EMBEDDING_MODEL_DEV = os.getenv("EMBEDDING_MODEL_DEV", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2").strip()
EMBEDDING_MODEL_CLOUD = os.getenv("EMBEDDING_MODEL_CLOUD", "text-multilingual-embedding-002").strip()

# Make the service-account path visible to Google client libs (cloud mode).
if GOOGLE_APPLICATION_CREDENTIALS:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
