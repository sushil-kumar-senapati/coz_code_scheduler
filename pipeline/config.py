import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "people's_priority")

SCHEDULER_TIME = os.getenv("SCHEDULER_TIME", "23:30")

# Google AI Studio API Key (Gemini 2.5 Flash — FREE tier)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")