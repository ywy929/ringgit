from datetime import datetime, timedelta
from unittest.mock import patch

from app.models import EmailAccount


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_fetch_refreshes_expired_token(client, db):
    past = _iso(datetime.utcnow() - timedelta(hours=1))
    acct = EmailAccount(
        email="u@gmail.com",
        access_token="at-stale",
        refresh_token="rt-good",
        token_expires_at=past,
    )
    db.add(acct)
    db.commit()

    with patch(
        "app.routers.email.refresh_access_token",
        return_value={"access_token": "at-fresh", "expires_at": _iso(datetime.utcnow() + timedelta(hours=1))},
    ) as mock_refresh, patch(
        "app.routers.email.GmailFetcher"
    ) as mock_fetcher_cls:
        mock_fetcher_cls.return_value.fetch_statements.return_value = []
        response = client.post("/api/email-accounts/fetch")

    assert response.status_code == 200
    mock_refresh.assert_called_once_with("rt-good")
    db.refresh(acct)
    assert acct.access_token == "at-fresh"


def test_fetch_skips_refresh_for_fresh_token(client, db):
    future = _iso(datetime.utcnow() + timedelta(hours=1))
    acct = EmailAccount(
        email="u@gmail.com",
        access_token="at-fresh",
        refresh_token="rt-any",
        token_expires_at=future,
    )
    db.add(acct)
    db.commit()

    with patch("app.routers.email.refresh_access_token") as mock_refresh, patch(
        "app.routers.email.GmailFetcher"
    ) as mock_fetcher_cls:
        mock_fetcher_cls.return_value.fetch_statements.return_value = []
        response = client.post("/api/email-accounts/fetch")

    assert response.status_code == 200
    mock_refresh.assert_not_called()
