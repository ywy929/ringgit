"""Environment-driven configuration loaded once at import time."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env relative to this file (backend/app/config.py)
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_ROOT / ".env")

GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI: str = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/oauth/callback"
)
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

BACKEND_ROOT: Path = _BACKEND_ROOT
