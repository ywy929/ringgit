from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models import EmailAccount


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_fetch_refreshes_expired_token(client, db):
    past = _iso(_utc_naive_now() - timedelta(hours=1))
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
        return_value={"access_token": "at-fresh", "expires_at": _iso(_utc_naive_now() + timedelta(hours=1))},
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
    future = _iso(_utc_naive_now() + timedelta(hours=1))
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


def test_fetch_persists_rotated_refresh_token(client, db):
    past = _iso(_utc_naive_now() - timedelta(hours=1))
    acct = EmailAccount(
        email="u@gmail.com",
        access_token="at-stale",
        refresh_token="rt-old",
        token_expires_at=past,
    )
    db.add(acct)
    db.commit()

    with patch(
        "app.routers.email.refresh_access_token",
        return_value={
            "access_token": "at-fresh",
            "refresh_token": "rt-rotated",
            "expires_at": _iso(_utc_naive_now() + timedelta(hours=1)),
        },
    ), patch("app.routers.email.GmailFetcher") as mock_fetcher_cls:
        mock_fetcher_cls.return_value.fetch_statements.return_value = []
        client.post("/api/email-accounts/fetch")

    db.refresh(acct)
    assert acct.refresh_token == "rt-rotated"


def test_fetch_marks_account_auth_failed_when_refresh_raises(client, db):
    # Two accounts: first refresh fails, second still gets fetched.
    from google.auth.exceptions import RefreshError
    past = _iso(_utc_naive_now() - timedelta(hours=1))
    bad = EmailAccount(email="bad@gmail.com", access_token="x",
                       refresh_token="rt-revoked", token_expires_at=past)
    good = EmailAccount(email="good@gmail.com", access_token="ok",
                        refresh_token="rt-good", token_expires_at=past)
    db.add_all([bad, good])
    db.commit()

    def _refresh(rt):
        if rt == "rt-revoked":
            raise RefreshError("invalid_grant")
        return {"access_token": "at-fresh", "refresh_token": rt,
                "expires_at": _iso(_utc_naive_now() + timedelta(hours=1))}

    with patch("app.routers.email.refresh_access_token", side_effect=_refresh), \
         patch("app.routers.email.GmailFetcher") as mock_fetcher_cls:
        mock_fetcher_cls.return_value.fetch_statements.return_value = []
        response = client.post("/api/email-accounts/fetch")

    assert response.status_code == 200
    body = response.json()
    by_email = {r["email"]: r for r in body}

    assert by_email["bad@gmail.com"]["status"] == "auth_failed"
    assert "invalid_grant" in by_email["bad@gmail.com"]["error_message"]
    assert by_email["bad@gmail.com"]["statements_found"] == 0

    # The other account was unaffected — proving one bad token doesn't bomb
    # the whole loop.
    assert by_email["good@gmail.com"]["status"] == "ok"


def test_fetch_marks_account_fetch_failed_when_gmail_raises(client, db):
    future = _iso(_utc_naive_now() + timedelta(hours=1))
    acct = EmailAccount(email="net@gmail.com", access_token="ok",
                        refresh_token="rt", token_expires_at=future)
    db.add(acct)
    db.commit()

    with patch("app.routers.email.GmailFetcher") as mock_fetcher_cls:
        mock_fetcher_cls.return_value.fetch_statements.side_effect = ConnectionError("boom")
        response = client.post("/api/email-accounts/fetch")

    assert response.status_code == 200
    result = response.json()[0]
    assert result["status"] == "fetch_failed"
    assert "boom" in result["error_message"]


def test_fetch_keeps_old_refresh_token_when_not_rotated(client, db):
    past = _iso(_utc_naive_now() - timedelta(hours=1))
    acct = EmailAccount(
        email="u@gmail.com",
        access_token="at-stale",
        refresh_token="rt-keep",
        token_expires_at=past,
    )
    db.add(acct)
    db.commit()

    with patch(
        "app.routers.email.refresh_access_token",
        return_value={
            "access_token": "at-fresh",
            "refresh_token": None,
            "expires_at": _iso(_utc_naive_now() + timedelta(hours=1)),
        },
    ), patch("app.routers.email.GmailFetcher") as mock_fetcher_cls:
        mock_fetcher_cls.return_value.fetch_statements.return_value = []
        client.post("/api/email-accounts/fetch")

    db.refresh(acct)
    assert acct.refresh_token == "rt-keep"


def test_fetch_does_not_advance_cursor_when_no_attachments(client, db):
    # Pre-existing cursor should NOT change when 0 attachments are returned.
    past = _iso(_utc_naive_now() - timedelta(hours=24))
    acct = EmailAccount(
        email="empty@gmail.com",
        access_token="at",
        refresh_token="rt",
        token_expires_at=_iso(_utc_naive_now() + timedelta(hours=1)),
        last_fetched_at=past,
    )
    db.add(acct); db.commit()

    with patch("app.routers.email.GmailFetcher") as mock_fetcher_cls:
        mock_fetcher_cls.return_value.fetch_statements.return_value = []
        client.post("/api/email-accounts/fetch")

    db.refresh(acct)
    assert acct.last_fetched_at == past, "cursor should not advance on empty fetch"


def test_fetch_advances_cursor_when_attachments_found(client, db, monkeypatch):
    # Pre-existing cursor SHOULD update when ≥1 attachment is processed.
    past = _iso(_utc_naive_now() - timedelta(hours=24))
    acct = EmailAccount(
        email="busy@gmail.com",
        access_token="at",
        refresh_token="rt",
        token_expires_at=_iso(_utc_naive_now() + timedelta(hours=1)),
        last_fetched_at=past,
    )
    db.add(acct); db.commit()

    # Stub _process_fetched_pdf to avoid PDF-extraction side effects.
    from app.schemas import UploadResult
    monkeypatch.setattr(
        "app.routers.email._process_fetched_pdf",
        lambda *a, **kw: UploadResult(
            filename="x.pdf", bank="unknown",
            transactions_imported=0, duplicates_skipped=0, status="failed",
        ),
    )

    with patch("app.routers.email.GmailFetcher") as mock_fetcher_cls:
        mock_fetcher_cls.return_value.fetch_statements.return_value = [
            {"filename": "x.pdf", "content": b"%PDF-1.4 dummy", "sender": "x@y.com"},
        ]
        client.post("/api/email-accounts/fetch")

    db.refresh(acct)
    assert acct.last_fetched_at != past, "cursor should advance when attachments processed"
