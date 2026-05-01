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

# Per-sender PDF passwords. Looked up by the lowercased sender email address
# in the email-fetch path. None means "no password configured" — the PDF
# falls through to the encrypted-stub path so the user can upload manually.
def _pw(env_var: str) -> str | None:
    v = os.getenv(env_var)
    return v if v else None

SENDER_PASSWORDS: dict[str, str | None] = {
    "ewallet@tngdigital.com.my": _pw("PDF_PASSWORD_TNG"),
    "estatement@aeonrewards.com.my": _pw("PDF_PASSWORD_AEON"),
}
