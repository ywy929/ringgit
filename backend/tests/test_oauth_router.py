from unittest.mock import patch

from app.models import EmailAccount


def test_oauth_start_redirects_to_google(client):
    with patch("app.routers.oauth.build_auth_url", return_value="https://accounts.google.com/fake"):
        response = client.get("/api/oauth/start", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "https://accounts.google.com/fake"


def test_oauth_callback_creates_email_account(client, db):
    from app.routers.oauth import _pending_states
    _pending_states.clear()  # isolate from any state leaked by earlier tests

    # Prime: trigger /start to register a state token.
    with patch("app.routers.oauth.build_auth_url", return_value="https://x/") as mock_auth:
        client.get("/api/oauth/start", follow_redirects=False)
    # Read the state that /start actually generated (passed as kwarg to build_auth_url).
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


def test_oauth_callback_rejects_invalid_state(client):
    response = client.get(
        "/api/oauth/callback?code=abc&state=not-registered",
        follow_redirects=False,
    )
    assert response.status_code == 400
