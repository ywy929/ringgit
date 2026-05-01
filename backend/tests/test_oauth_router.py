import time
from unittest.mock import patch

from app.models import EmailAccount, OAuthState


def test_oauth_start_redirects_to_google(client):
    with patch("app.routers.oauth.build_auth_url", return_value="https://accounts.google.com/fake"):
        response = client.get("/api/oauth/start", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "https://accounts.google.com/fake"


def test_oauth_start_persists_state_to_db(client, db):
    with patch("app.routers.oauth.build_auth_url", return_value="https://x/") as mock_auth:
        client.get("/api/oauth/start", follow_redirects=False)
    state = mock_auth.call_args.kwargs["state"]

    row = db.query(OAuthState).filter_by(state=state).first()
    assert row is not None
    assert row.expires_at > time.time()


def test_oauth_callback_creates_email_account(client, db):
    # Prime: trigger /start to register a state token.
    with patch("app.routers.oauth.build_auth_url", return_value="https://x/") as mock_auth:
        client.get("/api/oauth/start", follow_redirects=False)
    state = mock_auth.call_args.kwargs["state"]

    with patch(
        "app.routers.oauth.exchange_code_for_tokens",
        return_value={
            "email": "user@gmail.com",
            "access_token": "at1",
            "refresh_token": "rt1",
            "expires_at": "2026-04-18T12:00:00",
        },
    ):
        response = client.get(
            f"/api/oauth/callback?code=fakecode&state={state}",
            follow_redirects=False,
        )
    assert response.status_code in (302, 307)
    assert "connected=user%40gmail.com" in response.headers["location"]

    row = db.query(EmailAccount).filter_by(email="user@gmail.com").first()
    assert row is not None
    assert row.access_token == "at1"
    assert row.refresh_token == "rt1"
    assert row.token_expires_at == "2026-04-18T12:00:00"

    # State is single-use and removed after consumption.
    assert db.query(OAuthState).filter_by(state=state).first() is None


def test_oauth_callback_rejects_invalid_state(client):
    response = client.get(
        "/api/oauth/callback?code=abc&state=not-registered",
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_oauth_callback_rejects_expired_state(client, db):
    # Insert a state row with past expiry — cleanup pass should drop it,
    # then callback returns 400 because the lookup misses.
    db.add(OAuthState(state="expired-token", expires_at=time.time() - 1))
    db.commit()

    response = client.get(
        "/api/oauth/callback?code=abc&state=expired-token",
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert db.query(OAuthState).filter_by(state="expired-token").first() is None


def test_oauth_callback_succeeds_with_state_persisted_before_restart(client, db):
    # Simulates a uvicorn --reload between /start and /callback: state was
    # written by a prior process, this process never saw the dict-era memory
    # but reads the row from the DB and accepts the callback.
    state = "state-from-previous-process"
    db.add(OAuthState(state=state, expires_at=time.time() + 600))
    db.commit()

    with patch(
        "app.routers.oauth.exchange_code_for_tokens",
        return_value={
            "email": "after-reload@gmail.com",
            "access_token": "at2",
            "refresh_token": "rt2",
            "expires_at": None,
        },
    ):
        response = client.get(
            f"/api/oauth/callback?code=c&state={state}",
            follow_redirects=False,
        )

    assert response.status_code in (302, 307)
    assert db.query(EmailAccount).filter_by(email="after-reload@gmail.com").first() is not None
