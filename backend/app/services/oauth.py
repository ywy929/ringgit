"""Google OAuth helper service.

Provides three functions wrapping google-auth-oauthlib + google-auth:
- build_auth_url(state): returns Google consent URL.
- exchange_code_for_tokens(code): swaps auth code for tokens + user email.
- refresh_access_token(refresh_token): returns a fresh access token.
"""
import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _make_flow() -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": _AUTH_URI,
                "token_uri": _TOKEN_URI,
                "redirect_uris": [GOOGLE_REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )


def build_auth_url(state: str) -> str:
    flow = _make_flow()
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )
    return url


def exchange_code_for_tokens(code: str) -> dict:
    flow = _make_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    resp = httpx.get(
        _USERINFO_URL,
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    email = resp.json()["email"]
    expires_at = creds.expiry.isoformat() if creds.expiry else None
    return {
        "email": email,
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expires_at": expires_at,
    }


def refresh_access_token(refresh_token: str) -> dict:
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )
    creds.refresh(Request())
    expires_at = creds.expiry.isoformat() if creds.expiry else None
    # creds.refresh_token is updated to the new value if Google rotated it,
    # otherwise stays as the input. Return it so the caller can persist.
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expires_at": expires_at,
    }
