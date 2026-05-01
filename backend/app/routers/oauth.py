"""OAuth consent flow endpoints.

State is persisted in the oauth_states table (10-minute TTL) so the flow
survives a uvicorn --reload between /start and /callback. Sufficient for
single-user local usage; no distributed session store needed.
"""
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import FRONTEND_URL
from app.database import get_db
from app.models import EmailAccount, OAuthState
from app.services.oauth import build_auth_url, exchange_code_for_tokens

router = APIRouter()

_STATE_TTL_SECONDS = 600


def _cleanup_expired_states(db: Session) -> None:
    db.query(OAuthState).filter(OAuthState.expires_at < time.time()).delete()
    db.commit()


@router.get("/api/oauth/start")
def oauth_start(db: Session = Depends(get_db)) -> RedirectResponse:
    _cleanup_expired_states(db)
    state = secrets.token_urlsafe(32)
    db.add(OAuthState(state=state, expires_at=time.time() + _STATE_TTL_SECONDS))
    db.commit()
    url = build_auth_url(state=state)
    return RedirectResponse(url=url, status_code=307)


@router.get("/api/oauth/callback")
def oauth_callback(code: str, state: str, db: Session = Depends(get_db)) -> RedirectResponse:
    _cleanup_expired_states(db)
    row = db.query(OAuthState).filter_by(state=state).first()
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    db.delete(row)
    db.commit()

    tokens = exchange_code_for_tokens(code)

    existing = db.query(EmailAccount).filter_by(email=tokens["email"]).first()
    if existing:
        existing.access_token = tokens["access_token"]
        existing.refresh_token = tokens["refresh_token"]
        existing.token_expires_at = tokens["expires_at"]
    else:
        db.add(EmailAccount(
            email=tokens["email"],
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            token_expires_at=tokens["expires_at"],
        ))
    db.commit()

    return RedirectResponse(
        url=f"{FRONTEND_URL}/settings?connected={quote(tokens['email'])}",
        status_code=307,
    )
