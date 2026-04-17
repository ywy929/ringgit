# Blocking Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ringgit usable end-to-end on the author's machine by adding a real Gmail OAuth flow, persisting fetched PDFs to disk, providing a parser-iteration dev script, and writing a root README.

**Architecture:** Four sequential phases. Phase 1 adds `/api/oauth/start` + `/api/oauth/callback` to the FastAPI backend, stores `access_token` / `refresh_token` / `token_expires_at` on `EmailAccount`, loads `client_id` / `client_secret` from `backend/.env`, and replaces the Settings "paste token" UI with a "Connect Gmail" button. Phase 2 writes every fetched PDF to `backend/fetched_pdfs/<email_slug>/<YYYYMM>_<bank>_<hash8>.pdf` and records the path on `Statement.file_path`. Phase 3 adds `backend/scripts/replay_statement.py` for reparsing saved PDFs without Gmail round-trips. Phase 4 writes the root `README.md`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, pytest, `google-auth-oauthlib` (already in `requirements.txt`), `python-dotenv` (new), React 19 + TypeScript + Vite + Tailwind (frontend unchanged except Settings page).

**Reference spec:** `docs/superpowers/specs/2026-04-18-blocking-gaps-design.md`

---

## File Map

### New files
- `backend/.gitignore` — secret + db + PDF-backup patterns
- `backend/.env.example` — template for Google OAuth credentials
- `backend/app/config.py` — env-var loader
- `backend/app/services/oauth.py` — Google OAuth service (3 functions)
- `backend/app/routers/oauth.py` — `/api/oauth/start` + `/api/oauth/callback`
- `backend/tests/test_oauth_service.py` — service unit tests
- `backend/tests/test_oauth_router.py` — router integration tests
- `backend/tests/test_pdf_backup.py` — PDF-write-to-disk tests
- `backend/tests/test_parser_warning.py` — zero-parse warning test
- `backend/scripts/__init__.py` — package marker (empty)
- `backend/scripts/replay_statement.py` — developer tool
- `backend/tests/test_replay_script.py` — script smoke test
- `backend/tests/_real_pdf_helper.py` — helper for skip-if-missing fixture tests
- `backend/tests/test_real_pdfs.py` — skipped-by-default per-bank fixture tests
- `backend/tests/fixtures/real/.gitkeep` — directory marker
- `README.md` — repo-root quickstart + setup walkthrough

### Modified files
- `backend/requirements.txt` — add `python-dotenv==1.0.1`
- `backend/app/models.py` — `EmailAccount` token columns; add `Statement.file_path`
- `backend/app/schemas.py` — remove `EmailAccountCreate`
- `backend/app/main.py` — register new `oauth` router
- `backend/app/routers/email.py` — remove `POST /api/email-accounts`; restructure `_process_fetched_pdf` for write-before-parse; add refresh logic in `fetch_all_accounts`; add zero-parse warning
- `frontend/src/pages/Settings.tsx` — replace manual-token form with "Connect Gmail" button + `?connected=` toast handler
- `frontend/src/api/client.ts` — drop any `createEmailAccount` helper
- `frontend/src/types.ts` — drop the field no longer returned, if any

---

## Task 1: Gitignore protection (runs first so secrets and the dev DB never get tracked)

**Files:**
- Create: `backend/.gitignore`

- [ ] **Step 1: Create `backend/.gitignore`**

Write the following to `backend/.gitignore`:

```
# Environment / secrets
.env

# SQLite dev database
ringgit.db
ringgit.db-journal
test_ringgit.db
test_ringgit.db-journal

# Fetched PDFs (backup of real bank statements)
fetched_pdfs/

# Real-PDF regression fixtures (contain personal data)
tests/fixtures/real/

# Python bytecode / venv
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
```

- [ ] **Step 2: Verify no sensitive files are already tracked**

Run: `git ls-files backend | grep -E '\.env$|ringgit\.db$|fetched_pdfs/'`
Expected: no output (nothing tracked that will be newly ignored).

- [ ] **Step 3: Commit**

```bash
git add backend/.gitignore
git commit -m "chore(ringgit): gitignore env, sqlite dbs, and pdf backups"
```

---

## Task 2: Config module + python-dotenv + .env.example

**Files:**
- Modify: `backend/requirements.txt` (add `python-dotenv==1.0.1`)
- Create: `backend/app/config.py`
- Create: `backend/.env.example`

- [ ] **Step 1: Add `python-dotenv` to `backend/requirements.txt`**

Append `python-dotenv==1.0.1` as the last line of `backend/requirements.txt`.

- [ ] **Step 2: Install the new dep**

Run: `cd backend && pip install -r requirements.txt`
Expected: `Successfully installed python-dotenv-1.0.1` (or "Requirement already satisfied").

- [ ] **Step 3: Create `backend/app/config.py`**

```python
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
```

- [ ] **Step 4: Create `backend/.env.example`**

```
# Copy this file to .env and fill in values from Google Cloud Console.
# See README.md "Google Cloud setup" for the one-time setup walkthrough.
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/oauth/callback
FRONTEND_URL=http://localhost:5173
```

- [ ] **Step 5: Verify config imports cleanly**

Run: `cd backend && python -c "from app.config import GOOGLE_CLIENT_ID, BACKEND_ROOT; print(repr(GOOGLE_CLIENT_ID), BACKEND_ROOT)"`
Expected: `'' WindowsPath('C:/Users/aquam/Projects/ringgit/backend')` (empty client id, backend path resolved).

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/.env.example
git commit -m "chore(ringgit): add python-dotenv and config module"
```

---

## Task 3: Schema changes (EmailAccount tokens + Statement.file_path)

**Files:**
- Modify: `backend/app/models.py`
- Delete: `backend/ringgit.db` (drop-and-reseed; no real data yet)

- [ ] **Step 1: Update `EmailAccount` model**

In `backend/app/models.py`, replace the `EmailAccount` class (currently around lines 78-84) with:

```python
class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_fetched_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
```

- [ ] **Step 2: Add `file_path` to `Statement` model**

In `backend/app/models.py`, inside the `Statement` class, add after the `period_month` line:

```python
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

- [ ] **Step 3: Delete the dev SQLite database**

Run: `rm -f backend/ringgit.db backend/ringgit.db-journal`
Expected: no error; files gone (or never existed).

- [ ] **Step 4: Trigger schema creation directly (no server start needed)**

Run: `cd backend && python -c "from app.database import Base, engine; from app.models import *; Base.metadata.create_all(bind=engine); print('schema ok')"`
Expected: prints `schema ok` with no SQLAlchemy errors. A fresh `ringgit.db` now exists with the new columns (`email_accounts.access_token`, `email_accounts.refresh_token`, `email_accounts.token_expires_at`, `statements.file_path`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py
git commit -m "refactor(ringgit): email_account token columns and statement file_path"
```

---

## Task 4: OAuth service (TDD)

**Files:**
- Create: `backend/app/services/oauth.py`
- Create: `backend/tests/test_oauth_service.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_oauth_service.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from app.services import oauth


@patch("app.services.oauth.Flow")
def test_build_auth_url_sets_scope_and_prompt(mock_flow_cls):
    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = ("https://accounts.google.com/fake?state=xyz", "xyz")
    mock_flow_cls.from_client_config.return_value = mock_flow

    url = oauth.build_auth_url(state="xyz")

    mock_flow.authorization_url.assert_called_once_with(
        access_type="offline",
        prompt="consent",
        state="xyz",
    )
    config_arg = mock_flow_cls.from_client_config.call_args
    assert "gmail.readonly" in config_arg.kwargs["scopes"][0]
    assert url == "https://accounts.google.com/fake?state=xyz"


@patch("app.services.oauth.httpx")
@patch("app.services.oauth.Flow")
def test_exchange_code_for_tokens_returns_parsed_fields(mock_flow_cls, mock_httpx):
    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_creds.token = "at-new"
    mock_creds.refresh_token = "rt-new"
    mock_creds.expiry = None
    mock_flow.credentials = mock_creds
    mock_flow_cls.from_client_config.return_value = mock_flow

    mock_response = MagicMock()
    mock_response.json.return_value = {"email": "user@gmail.com"}
    mock_httpx.get.return_value = mock_response

    result = oauth.exchange_code_for_tokens("fake-code")

    mock_flow.fetch_token.assert_called_once_with(code="fake-code")
    assert result == {
        "email": "user@gmail.com",
        "access_token": "at-new",
        "refresh_token": "rt-new",
        "expires_at": None,
    }


@patch("app.services.oauth.Credentials")
def test_refresh_access_token_uses_refresh_token(mock_creds_cls):
    mock_creds = MagicMock()
    mock_creds.token = "at-refreshed"
    mock_creds.expiry = None
    mock_creds_cls.return_value = mock_creds

    result = oauth.refresh_access_token("rt-old")

    mock_creds.refresh.assert_called_once()
    assert result == {"access_token": "at-refreshed", "expires_at": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_oauth_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.oauth'`.

- [ ] **Step 3: Implement `backend/app/services/oauth.py`**

```python
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
    return {"access_token": creds.token, "expires_at": expires_at}
```

Note: `httpx` is already a direct dep (`requirements.txt:7`); no dep change needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_oauth_service.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/oauth.py backend/tests/test_oauth_service.py
git commit -m "feat(ringgit): add google oauth service with tests"
```

---

## Task 5: OAuth router endpoints (TDD)

**Files:**
- Create: `backend/app/routers/oauth.py`
- Create: `backend/tests/test_oauth_router.py`
- Modify: `backend/app/main.py` (register new router)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_oauth_router.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_oauth_router.py -v`
Expected: FAIL with `404` or import errors on the new module.

- [ ] **Step 3: Implement `backend/app/routers/oauth.py`**

```python
"""OAuth consent flow endpoints.

State is kept in a process-local dict with a 10-minute TTL — sufficient for
single-user local usage; no distributed session store needed.
"""
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import FRONTEND_URL
from app.database import get_db
from app.models import EmailAccount
from app.services.oauth import build_auth_url, exchange_code_for_tokens

router = APIRouter()

_STATE_TTL_SECONDS = 600
_pending_states: dict[str, float] = {}


def _cleanup_expired_states() -> None:
    now = time.time()
    for key in [k for k, exp in _pending_states.items() if exp < now]:
        _pending_states.pop(key, None)


@router.get("/api/oauth/start")
def oauth_start() -> RedirectResponse:
    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _pending_states[state] = time.time() + _STATE_TTL_SECONDS
    url = build_auth_url(state=state)
    return RedirectResponse(url=url, status_code=307)


@router.get("/api/oauth/callback")
def oauth_callback(code: str, state: str, db: Session = Depends(get_db)) -> RedirectResponse:
    _cleanup_expired_states()
    if state not in _pending_states:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    _pending_states.pop(state, None)

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

    from urllib.parse import quote
    return RedirectResponse(
        url=f"{FRONTEND_URL}/settings?connected={quote(tokens['email'])}",
        status_code=307,
    )
```

- [ ] **Step 4: Register router in `backend/app/main.py`**

In `backend/app/main.py`, modify the routers import at line 7 to also import `oauth`:

```python
from app.routers import accounts, budgets, categories, dashboard, email, oauth, transactions, upload
```

And add after the other `app.include_router(...)` calls (after line 39):

```python
app.include_router(oauth.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_oauth_router.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/oauth.py backend/tests/test_oauth_router.py backend/app/main.py
git commit -m "feat(ringgit): add oauth consent and callback endpoints"
```

---

## Task 6: Token refresh in fetch_all_accounts (TDD)

**Files:**
- Modify: `backend/app/routers/email.py` (the `fetch_all_accounts` function, around lines 189-215)
- Create: `backend/tests/test_email_fetch_refresh.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_email_fetch_refresh.py`:

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models import EmailAccount


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_email_fetch_refresh.py -v`
Expected: FAIL. Either `AttributeError: app.routers.email has no 'refresh_access_token'` or stale-field access errors on the old `oauth_token`.

- [ ] **Step 3: Update `fetch_all_accounts` and its helpers in `backend/app/routers/email.py`**

At the top of `backend/app/routers/email.py`, ensure these imports exist (add if missing):

```python
from datetime import datetime

from app.services.oauth import refresh_access_token
```

Replace the existing `fetch_all_accounts` function (currently lines 189-215) with:

```python
_REFRESH_SKEW_SECONDS = 60


def _token_near_expiry(expires_at_iso: str | None) -> bool:
    if not expires_at_iso:
        return True
    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except ValueError:
        return True
    return datetime.utcnow().timestamp() >= expires_at.timestamp() - _REFRESH_SKEW_SECONDS


@router.post("/api/email-accounts/fetch", response_model=list[FetchResult])
def fetch_all_accounts(db: Session = Depends(get_db)):
    accounts = db.query(EmailAccount).all()
    results = []

    for acct in accounts:
        if _token_near_expiry(acct.token_expires_at) and acct.refresh_token:
            refreshed = refresh_access_token(acct.refresh_token)
            acct.access_token = refreshed["access_token"]
            acct.token_expires_at = refreshed["expires_at"]
            db.commit()

        credentials = Credentials(token=acct.access_token)
        fetcher = GmailFetcher(credentials)

        after_date = acct.last_fetched_at[:10] if acct.last_fetched_at else None
        attachments = fetcher.fetch_statements(after_date=after_date)

        processed = []
        for att in attachments:
            result = _process_fetched_pdf(att["filename"], att["content"], db)
            processed.append(result)

        acct.last_fetched_at = datetime.utcnow().isoformat()
        db.commit()

        results.append(FetchResult(
            email=acct.email,
            statements_found=len(attachments),
            statements_processed=processed,
        ))

    return results
```

Note: the `_process_fetched_pdf(...)` call keeps its current 3-argument shape here. Task 9 changes the signature to `(filename, content, db, email)` and updates this caller to pass `acct.email` in the same commit.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_email_fetch_refresh.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run full test suite to catch regressions**

Run: `cd backend && pytest -v`
Expected: all passing. If `test_gmail_fetcher.py` breaks due to the `oauth_token` rename, update it now (replace `oauth_token=` with `access_token=` anywhere a literal `EmailAccount(...)` is constructed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/email.py backend/tests/test_email_fetch_refresh.py backend/tests/test_gmail_fetcher.py
git commit -m "feat(ringgit): auto-refresh expired gmail tokens on fetch"
```

---

## Task 7: Remove deprecated POST /api/email-accounts

**Files:**
- Modify: `backend/app/routers/email.py`
- Modify: `backend/app/schemas.py`

- [ ] **Step 1: Remove the POST endpoint**

In `backend/app/routers/email.py`, delete the entire `add_email_account` function (currently lines 163-176):

```python
@router.post("/api/email-accounts", response_model=EmailAccountResponse)
def add_email_account(payload: EmailAccountCreate, db: Session = Depends(get_db)):
    ...
```

Also remove the now-unused import `EmailAccountCreate` from the imports block at the top of the file.

- [ ] **Step 2: Remove `EmailAccountCreate` from schemas**

In `backend/app/schemas.py`, delete the class (currently around lines 104-106):

```python
class EmailAccountCreate(BaseModel):
    email: str
    oauth_token: str
```

- [ ] **Step 3: Run the full test suite**

Run: `cd backend && pytest -v`
Expected: all passing. No tests should reference `EmailAccountCreate`.

- [ ] **Step 4: Verify no other code imports it**

Run: `grep -r "EmailAccountCreate" backend/`
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/email.py backend/app/schemas.py
git commit -m "refactor(ringgit): drop deprecated manual token upsert endpoint"
```

---

## Task 8: Frontend Settings "Connect Gmail" button

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/api/client.ts` (if it currently exports a `createEmailAccount` helper)

- [ ] **Step 1: Check for any existing `createEmailAccount` call in the frontend**

Run: `grep -rn "createEmailAccount\|oauth_token" frontend/src`
If matches exist, note which files need cleanup.

- [ ] **Step 2: Remove `createEmailAccount` from `frontend/src/api/client.ts`**

If the file exports any helper that POSTs to `/api/email-accounts` with an `oauth_token` body, delete the function and its type. Keep `getEmailAccounts` and `deleteEmailAccount`.

- [ ] **Step 3: Update the Gmail Accounts card in `frontend/src/pages/Settings.tsx`**

Locate the `{/* Gmail Accounts */}` block (around line 70-90). Replace the entire card body with a version that adds a "Connect Gmail" button under the email list:

```tsx
{/* Gmail Accounts */}
<div className="ledger-card animate-reveal animate-reveal-1">
  <div className="ledger-card-header">Gmail Accounts</div>
  <div className="p-5">
    {emails.length === 0 && <div className="text-sm text-ink-whisper">No email accounts connected</div>}
    {emails.map(em => (
      <div key={em.id} className="flex items-center justify-between py-3 border-b border-rule last:border-b-0">
        <div>
          <span className="text-sm font-semibold text-ink">{em.email}</span>
          <span className="font-label text-xs text-ink-whisper ml-3">
            {em.last_fetched_at ? `Last fetched: ${new Date(em.last_fetched_at).toLocaleDateString('en-MY')}` : 'Never fetched'}
          </span>
        </div>
        <button onClick={() => handleDisconnectEmail(em.id)}
          className="text-xs font-bold uppercase tracking-wide text-negative hover:bg-negative hover:text-white px-3 py-1.5 rounded border border-negative transition-colors">
          Disconnect
        </button>
      </div>
    ))}
    <div className="pt-4 mt-2 border-t border-rule">
      <a href="http://localhost:8000/api/oauth/start"
        className="inline-block bg-accent-ink text-white font-bold text-sm uppercase tracking-wide px-5 py-2 rounded hover:bg-accent-deep transition-colors">
        Connect Gmail
      </a>
      <span className="ml-3 text-xs text-ink-whisper">Opens Google consent — you can connect multiple accounts.</span>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add the `?connected=` toast handler**

At the top of the `Settings` component (after the `useState` declarations, before the existing `reload` function), add:

```tsx
const [toast, setToast] = useState<string | null>(null)

useEffect(() => {
  const params = new URLSearchParams(window.location.search)
  const connected = params.get('connected')
  if (connected) {
    setToast(`Connected ${connected}`)
    window.history.replaceState({}, '', window.location.pathname)
    setTimeout(() => setToast(null), 4000)
  }
}, [])
```

And render the toast near the top of the returned JSX (right after the `<div>` that opens the component, before the Header div):

```tsx
{toast && (
  <div className="fixed top-6 right-6 bg-accent-ink text-white px-4 py-3 rounded shadow-lg z-50 text-sm font-semibold">
    {toast}
  </div>
)}
```

- [ ] **Step 5: Manually verify the page renders**

Run in one terminal: `cd backend && uvicorn app.main:app --reload`
Run in another: `cd frontend && npm install && npm run dev`
Open `http://localhost:5173/settings`.

Expected: Settings page renders, "Connect Gmail" button visible, clicking it navigates to `http://localhost:8000/api/oauth/start` which will fail without a valid `GOOGLE_CLIENT_ID` (expected — full e2e happens in Task 13 after Google Cloud setup is documented).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/api/client.ts
git commit -m "feat(ringgit): connect gmail button replaces manual token entry"
```

---

## Task 9: PDF backup to disk (TDD)

**Files:**
- Create: `backend/tests/test_pdf_backup.py`
- Modify: `backend/app/routers/email.py` (restructure `_process_fetched_pdf`)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_pdf_backup.py`:

```python
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models import Account, Statement
from app.routers.email import _process_fetched_pdf, PDF_ROOT


@pytest.fixture(autouse=True)
def _clean_pdf_root():
    yield
    if PDF_ROOT.exists():
        shutil.rmtree(PDF_ROOT)


def _seed_account(db, bank="maybank"):
    acc = Account(name="Test Maybank", bank=bank, type="savings")
    db.add(acc)
    db.commit()
    return acc


def _fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\nfake content for tests\n"


def test_fetched_pdf_written_to_disk_and_path_recorded(db):
    _seed_account(db)

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text): return [{"date": "2026-04-01", "description": "TEST", "amount": 10.0, "type": "debit"}]
        def extract_period_month(self, text): return "2026-04"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="MAYBANK STATEMENT OF ACCOUNT..."
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        result = _process_fetched_pdf("mbb.pdf", _fake_pdf_bytes(), db, "user@gmail.com")

    assert result.status == "done"
    stmt = db.query(Statement).first()
    assert stmt.file_path is not None
    full_path = PDF_ROOT.parent / stmt.file_path
    assert full_path.exists()
    assert full_path.read_bytes() == _fake_pdf_bytes()
    assert "user_gmail_com" in stmt.file_path
    assert "maybank" in stmt.file_path


def test_duplicate_pdf_not_rewritten(db):
    _seed_account(db)

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text): return []
        def extract_period_month(self, text): return "2026-04"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="text"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        # First call: writes the file.
        _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "user@gmail.com")
        stmt = db.query(Statement).first()
        written = PDF_ROOT.parent / stmt.file_path
        mtime_before = written.stat().st_mtime_ns

        # Second call with identical bytes: duplicate-skipped, no overwrite.
        result = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "user@gmail.com")
        assert result.status == "duplicate"
        assert written.stat().st_mtime_ns == mtime_before


def test_unknown_bank_still_writes_pdf(db):
    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="some text"
    ):
        mock_reg.detect_bank.return_value = None
        result = _process_fetched_pdf("unk.pdf", _fake_pdf_bytes(), db, "user@gmail.com")

    assert result.status == "failed"
    # Even on detection failure, bytes are preserved for later inspection.
    slug_dir = PDF_ROOT / "user_gmail_com"
    pdfs = list(slug_dir.glob("unknown_unknown_*.pdf"))
    assert len(pdfs) == 1
    assert pdfs[0].read_bytes() == _fake_pdf_bytes()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_pdf_backup.py -v`
Expected: FAIL — `ImportError: cannot import name 'PDF_ROOT'` and signature mismatch on `_process_fetched_pdf`.

- [ ] **Step 3: Restructure `_process_fetched_pdf` AND update its caller in `backend/app/routers/email.py`**

Two edits in one commit: the function signature change below, plus one line in `fetch_all_accounts` — find the existing call:

```python
result = _process_fetched_pdf(att["filename"], att["content"], db)
```

and change it to:

```python
result = _process_fetched_pdf(att["filename"], att["content"], db, acct.email)
```

Now for the function itself. At the top of the file, add these imports near the others:

```python
import logging
import re
from pathlib import Path

from app.config import BACKEND_ROOT

logger = logging.getLogger(__name__)

PDF_ROOT = BACKEND_ROOT / "fetched_pdfs"
```

Replace the entire existing `_process_fetched_pdf` function with:

```python
def _process_fetched_pdf(filename: str, content: bytes, db: Session, email: str) -> UploadResult:
    file_hash = hashlib.sha256(content).hexdigest()

    # Duplicate check first — avoid disk write on repeats.
    existing = db.query(Statement).filter_by(file_hash=file_hash).first()
    if existing:
        return UploadResult(
            filename=filename,
            bank="",
            transactions_imported=0,
            duplicates_skipped=1,
            status="duplicate",
            message="This statement has already been imported.",
        )

    # Extract text (no password for email PDFs).
    try:
        text = _extract_text_from_pdf(content)
    except Exception:
        return UploadResult(
            filename=filename,
            bank="unknown",
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message="Password-protected PDF. Please upload manually with the password.",
        )

    # Detect bank and period up-front so the saved filename is informative.
    parser = registry.detect_bank(text)
    if parser is None:
        bank_id = "unknown"
        period_month = "unknown"
    else:
        bank_id = parser.bank_id
        period_month = parser.extract_period_month(text) or "unknown"

    # Persist the PDF to disk before parsing runs, so a parser crash still
    # leaves the bytes available for inspection via replay_statement.py.
    email_slug = re.sub(r"\W+", "_", email)
    target_dir = PDF_ROOT / email_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{period_month}_{bank_id}_{file_hash[:8]}.pdf"
    target.write_bytes(content)
    file_path_rel = str(target.relative_to(BACKEND_ROOT))

    if parser is None:
        return UploadResult(
            filename=filename,
            bank="unknown",
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message="Could not detect bank from statement.",
        )

    account = db.query(Account).filter_by(bank=bank_id).first()
    if not account:
        return UploadResult(
            filename=filename,
            bank=bank_id,
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message=f"No account found for bank '{bank_id}'. Please create one first.",
        )

    parsed = parser.parse(text)

    stmt = Statement(
        file_hash=file_hash,
        bank=bank_id,
        source="email",
        filename=filename,
        period_month=period_month if period_month != "unknown" else "",
        file_path=file_path_rel,
    )
    db.add(stmt)
    db.flush()

    categorizer = Categorizer(db)
    uncat = db.query(Category).filter_by(name="Uncategorized").first()

    for p in parsed:
        cat_id = categorizer.categorize(p["description"])
        if cat_id is None and uncat:
            cat_id = uncat.id
        is_atm = bool(ATM_PATTERN.search(p["description"]))
        tx = Transaction(
            statement_id=stmt.id,
            account_id=account.id,
            date=p["date"],
            description=p["description"],
            amount=p["amount"],
            type=p["type"],
            category_id=cat_id,
            is_cash_withdrawal=is_atm,
        )
        db.add(tx)

    db.commit()

    if period_month and period_month != "unknown":
        TransferDetector(db).apply_transfers(period_month)
    RecurringDetector(db).apply_recurring_flags()

    # For the unknown-bank case we wrote the file but returned failed above;
    # reaching here means bank known. Still, warn if the parser produced nothing
    # meaningful from a non-trivial document.
    if len(parsed) == 0 and len(text.strip()) > 100:
        logger.warning(
            "parser %s returned 0 transactions for %s (%d chars extracted); sample: %r",
            bank_id, file_path_rel, len(text), text[:200],
        )

    return UploadResult(
        filename=filename,
        bank=bank_id,
        transactions_imported=len(parsed),
        duplicates_skipped=0,
        status="done",
    )
```

- [ ] **Step 4: Run the new tests**

Run: `cd backend && pytest tests/test_pdf_backup.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && pytest -v`
Expected: all passing. The refresh tests from Task 6 still pass because they mock `GmailFetcher` to return no attachments.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/email.py backend/tests/test_pdf_backup.py
git commit -m "feat(ringgit): persist fetched pdfs and record paths"
```

---

## Task 10: Parser zero-parse warning test (TDD)

The warning itself was added in Task 9. This task adds a dedicated test to pin the logging behavior so future refactors can't silently remove it.

**Files:**
- Create: `backend/tests/test_parser_warning.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_parser_warning.py`:

```python
import logging
from unittest.mock import patch

from app.models import Account
from app.routers.email import _process_fetched_pdf


class _SilentParser:
    bank_id = "maybank"
    def can_parse(self, text): return True
    def parse(self, text): return []
    def extract_period_month(self, text): return "2026-04"


def test_zero_parse_from_long_text_emits_warning(db, caplog):
    db.add(Account(name="A", bank="maybank", type="savings"))
    db.commit()

    long_text = "MAYBANK STATEMENT OF ACCOUNT " * 50
    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value=long_text
    ), caplog.at_level(logging.WARNING, logger="app.routers.email"):
        mock_reg.detect_bank.return_value = _SilentParser()
        _process_fetched_pdf("a.pdf", b"%PDF-1.4 fake", db, "u@g.com")

    matching = [r for r in caplog.records if "returned 0 transactions" in r.getMessage()]
    assert len(matching) == 1
    assert "maybank" in matching[0].getMessage()


def test_zero_parse_from_short_text_does_not_warn(db, caplog):
    db.add(Account(name="A", bank="maybank", type="savings"))
    db.commit()

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="short"
    ), caplog.at_level(logging.WARNING, logger="app.routers.email"):
        mock_reg.detect_bank.return_value = _SilentParser()
        _process_fetched_pdf("a.pdf", b"%PDF-1.4 fake", db, "u@g.com")

    matching = [r for r in caplog.records if "returned 0 transactions" in r.getMessage()]
    assert len(matching) == 0
```

- [ ] **Step 2: Run tests to verify outcome**

Run: `cd backend && pytest tests/test_parser_warning.py -v`
Expected: 2 passed (the warning code was already added in Task 9; these tests pin the behavior).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_parser_warning.py
git commit -m "test(ringgit): pin zero-parse warning behavior"
```

---

## Task 11: Replay-statement dev script

**Files:**
- Create: `backend/scripts/__init__.py`
- Create: `backend/scripts/replay_statement.py`
- Create: `backend/tests/test_replay_script.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_replay_script.py`:

```python
import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_statement.py"


def _make_pdf_with_text(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def test_replay_exits_nonzero_for_unknown_bank(tmp_path):
    pdf = tmp_path / "mystery.pdf"
    _make_pdf_with_text(pdf, "this does not look like any bank statement")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(pdf)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "no parser matched" in result.stdout.lower() or "no parser matched" in result.stderr.lower()


def test_replay_exits_zero_when_parser_finds_transactions(tmp_path):
    # Use the committed maybank text fixture as a PDF.
    pdf = tmp_path / "maybank.pdf"
    sample_txt = Path(__file__).resolve().parents[1] / "sample_data" / "maybank_sample.txt"
    _make_pdf_with_text(pdf, sample_txt.read_text())

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(pdf)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "maybank" in result.stdout.lower()
    assert "transactions parsed" in result.stdout.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_replay_script.py -v`
Expected: FAIL — script does not exist.

- [ ] **Step 3: Create the package marker**

Create empty file `backend/scripts/__init__.py` (zero bytes).

- [ ] **Step 4: Implement `backend/scripts/replay_statement.py`**

```python
"""Replay a saved PDF through the parser registry.

Usage: python scripts/replay_statement.py <path-to-pdf>

Exits 0 if >=1 transaction parsed, 1 otherwise. Useful for iterating on a
parser's regexes without re-fetching from Gmail.
"""
import sys
from pathlib import Path

# Allow running this script directly from anywhere inside the backend dir.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # PyMuPDF

from app.services.parser_registry import ParserRegistry


def _extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def main(pdf_path: Path) -> int:
    text = _extract_text(pdf_path)
    registry = ParserRegistry()
    parser = registry.detect_bank(text)
    if parser is None:
        print(f"no parser matched for {pdf_path}")
        print(f"extracted text length: {len(text)} chars")
        print(f"first 200 chars: {text[:200]!r}")
        return 1

    bank = parser.bank_id
    period = parser.extract_period_month(text)
    transactions = parser.parse(text)

    print(f"bank detected: {bank}")
    print(f"period_month: {period}")
    print(f"transactions parsed: {len(transactions)}")
    print("first 5:")
    for t in transactions[:5]:
        date = t.get("date") if isinstance(t, dict) else t.date
        desc = t.get("description") if isinstance(t, dict) else t.description
        amount = t.get("amount") if isinstance(t, dict) else t.amount
        ttype = t.get("type") if isinstance(t, dict) else t.type
        print(f"  {date}  {desc[:30]:30s}  {amount:>10.2f}  {ttype}")

    return 0 if len(transactions) > 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/replay_statement.py <path-to-pdf>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_replay_script.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/__init__.py backend/scripts/replay_statement.py backend/tests/test_replay_script.py
git commit -m "feat(ringgit): add replay_statement dev script for parser iteration"
```

---

## Task 12: Per-bank real-PDF regression test skeleton

**Files:**
- Create: `backend/tests/fixtures/real/.gitkeep`
- Create: `backend/tests/_real_pdf_helper.py`
- Create: `backend/tests/test_real_pdfs.py`

- [ ] **Step 1: Create the fixture directory marker**

Create `backend/tests/fixtures/real/.gitkeep` with this content:

```
Drop real bank-statement PDFs here as you validate each parser.
Filenames: <bank>_<YYYYMM>.pdf (e.g. maybank_202603.pdf).
This directory is gitignored; the PDFs stay on your machine only.
```

- [ ] **Step 2: Create the helper module**

Create `backend/tests/_real_pdf_helper.py`:

```python
"""Helper for real-PDF regression tests.

Each parser gets one `test_<bank>_real` test that loads
`backend/tests/fixtures/real/<bank>_<YYYYMM>.pdf` — gitignored — and asserts
basic parse counts. When the file is missing (fresh clone, CI) the test skips.
"""
from pathlib import Path

import fitz  # PyMuPDF
import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "real"


def load_real_pdf_text(filename: str) -> str | None:
    """Return extracted text, or None if the fixture is absent."""
    path = FIXTURE_DIR / filename
    if not path.exists():
        return None
    doc = fitz.open(str(path))
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def skip_if_no_fixture(filename: str):
    """Decorator factory: skips the test when the fixture file is absent."""
    return pytest.mark.skipif(
        not (FIXTURE_DIR / filename).exists(),
        reason=f"real fixture {filename} not present (drop into {FIXTURE_DIR} to enable)",
    )
```

- [ ] **Step 3: Create the per-bank test file**

Create `backend/tests/test_real_pdfs.py`:

```python
"""Per-bank regression tests against real PDF fixtures.

Each test is skipped on a fresh clone (fixture absent). As each bank's parser
is validated, drop the fixture PDF into tests/fixtures/real/, update the
expected_min_transactions to the known count, and unskip by committing the
fixture on YOUR machine (still gitignored — numbers stay in the test).
"""
from app.services.parsers.aeon import AeonParser
from app.services.parsers.cimb import CimbParser
from app.services.parsers.hong_leong import HongLeongParser
from app.services.parsers.maybank import MaybankParser
from app.services.parsers.public_bank import PublicBankParser
from app.services.parsers.tng import TngParser

from tests._real_pdf_helper import load_real_pdf_text, skip_if_no_fixture


@skip_if_no_fixture("maybank_202603.pdf")
def test_maybank_real_pdf():
    text = load_real_pdf_text("maybank_202603.pdf")
    parser = MaybankParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1, f"expected >=1 maybank transactions, got {len(txs)}"


@skip_if_no_fixture("cimb_202603.pdf")
def test_cimb_real_pdf():
    text = load_real_pdf_text("cimb_202603.pdf")
    parser = CimbParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1


@skip_if_no_fixture("public_bank_202603.pdf")
def test_public_bank_real_pdf():
    text = load_real_pdf_text("public_bank_202603.pdf")
    parser = PublicBankParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1


@skip_if_no_fixture("hong_leong_202603.pdf")
def test_hong_leong_real_pdf():
    text = load_real_pdf_text("hong_leong_202603.pdf")
    parser = HongLeongParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1


@skip_if_no_fixture("tng_202603.pdf")
def test_tng_real_pdf():
    text = load_real_pdf_text("tng_202603.pdf")
    parser = TngParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1


@skip_if_no_fixture("aeon_202603.pdf")
def test_aeon_real_pdf():
    text = load_real_pdf_text("aeon_202603.pdf")
    parser = AeonParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1
```

- [ ] **Step 4: Verify all tests skip on a fresh clone**

Run: `cd backend && pytest tests/test_real_pdfs.py -v`
Expected: 6 skipped (no fixtures present yet). Output mentions "real fixture … not present".

- [ ] **Step 5: Commit**

The actual `.gitkeep` should be tracked (it's a skeleton placeholder). The `fixtures/real/*.pdf` paths are gitignored per Task 1, so only the `.gitkeep` and the test files are tracked.

```bash
git add backend/tests/fixtures/real/.gitkeep backend/tests/_real_pdf_helper.py backend/tests/test_real_pdfs.py
git commit -m "test(ringgit): add skipped-by-default real-PDF regression harness"
```

---

## Task 13: Root README.md

**Files:**
- Create: `README.md` (at repo root)

- [ ] **Step 1: Create `README.md`**

Write the following to `README.md` at the repo root (`C:\Users\aquam\Projects\ringgit\README.md`):

```markdown
# Ringgit

A local-only personal finance analyzer for Malaysian bank statements. Ingests PDFs from Maybank, CIMB, Public Bank, Hong Leong, AEON Credit, and Touch 'n Go — either via manual upload or automatic Gmail fetch — auto-categorizes transactions (bilingual keyword matching), detects internal transfers between your own accounts, flags recurring charges, and shows a monthly dashboard with a budget target.

Single-user. No authentication. Runs on your own machine.

Full product documentation lives outside this repo in the author's `PersonalVault/projects/ringgit-financial-analyzer` directory.

## Quickstart

You need **Python 3.11+** and **Node 20+**.

In two terminals:

```bash
# Terminal 1: backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
# → http://localhost:8000  (API + docs at /docs)
```

```bash
# Terminal 2: frontend
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

On first boot the backend creates `ringgit.db` and seeds default categories + keywords.

## Google Cloud setup (one-time, required for Gmail auto-fetch)

Without these steps, manual PDF upload still works but "Connect Gmail" will fail.

1. Go to <https://console.cloud.google.com> and create a new project (any name).
2. **APIs & Services → Library → Gmail API → Enable.**
3. **APIs & Services → OAuth consent screen.** Choose *External*, fill in app name / email, and under *Test users* add the Gmail addresses you plan to connect. Leave publishing status as *Testing*.
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID.** Application type: **Web application**.
5. Under *Authorized redirect URIs*, add: `http://localhost:8000/api/oauth/callback`.
6. Copy the Client ID and Client Secret into `backend/.env`:

```bash
cp backend/.env.example backend/.env
# then edit backend/.env and paste the values
```

Restart the backend after editing `.env`.

> Because the consent screen is in *Testing* mode, Google shows an "unverified app" interstitial on first consent. That's expected — click "Advanced → Continue to <project name>".

## Connecting a Gmail account

1. Ensure both backend and frontend are running.
2. Go to Settings → **Connect Gmail**.
3. Pick the Google account, accept permissions — you're redirected back with a "Connected …" toast.
4. Repeat for your second Gmail if you have one.
5. The app fetches statements automatically on next boot, or trigger a fetch from the UI.

## Troubleshooting

**Parser returned 0 transactions.** The parser's regex/column offsets don't match this bank's real PDF layout. Find the saved PDF under `backend/fetched_pdfs/<email_slug>/` and inspect:

```bash
cd backend
python scripts/replay_statement.py fetched_pdfs/you_gmail_com/202603_maybank_a1b2c3d4.pdf
```

The script prints the detected bank, transaction count, and the first five rows. Adjust the regex in `backend/app/services/parsers/<bank>.py` and re-run the script until transactions appear.

**Gmail fetch fails with 401 / "token refresh failed".** The refresh token was revoked (manual revoke at <https://myaccount.google.com/permissions>, or >6 months of inactivity). Click **Connect Gmail** again for that account to re-consent.

**Frontend shows "No account found for bank …" after fetch.** You haven't created a bank account in Settings yet whose `bank` field matches the parser's bank ID (e.g. `maybank`, `cimb`). Add one in Settings → Bank Accounts.

## Repo layout

```
backend/
  app/
    routers/        # FastAPI endpoints
    services/       # parsers, categorizer, fetcher, detectors, oauth
    models.py       # SQLAlchemy models
    schemas.py      # Pydantic request/response schemas
  scripts/          # dev tools (replay_statement.py)
  tests/            # pytest suite
  fetched_pdfs/     # gitignored — backup of real statements
  sample_data/      # text fixtures for parser development
frontend/
  src/
    pages/          # Dashboard, Transactions, Upload, Budget, Settings
    api/            # typed API client
    components/     # shared UI
docs/superpowers/   # specs and plans (this doc lives under docs/superpowers/plans/)
```
```

- [ ] **Step 2: Sanity-check the file rendered**

Run: `cat README.md | head -40`
Expected: first 40 lines show the intro through the Quickstart section cleanly.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(ringgit): add root readme with quickstart and oauth setup"
```

---

## Post-plan: operational work (not tasks)

Two activities happen AFTER this plan ships. They are ongoing work, not plan tasks:

1. **Real-PDF parser validation.** As each Gmail-connected account delivers its first statement, run `python scripts/replay_statement.py <path>` on the saved PDF. For any bank that returns zero or obviously wrong transactions, tune the regex in `backend/app/services/parsers/<bank>.py`, rerun until clean, then drop a copy of the PDF into `backend/tests/fixtures/real/<bank>_<YYYYMM>.pdf` and the corresponding `test_<bank>_real_pdf` in `backend/tests/test_real_pdfs.py` starts running as a regression guard.

2. **First full e2e dry-run.** Follow the README end-to-end on your own machine: create OAuth credentials, paste into `.env`, connect both Gmail accounts, trigger fetch, verify transactions appear in the Dashboard. Any gap in the README gets patched as a follow-up commit.

---

## Self-review

**Spec coverage:** each section of `2026-04-18-blocking-gaps-design.md` is covered —
- Phase 1 OAuth: Tasks 1, 2, 3, 4, 5, 6, 7, 8.
- Phase 2 fetch+backup: Tasks 3 (file_path column), 9, 10.
- Phase 3 parser iteration: Tasks 11, 12.
- Phase 4 README: Task 13.
- Scope exclusions (no auth, no encryption, no Alembic, no retries) — all respected by omission.

**Placeholder scan:** no TBD/TODO markers, every step has concrete code or a concrete command.

**Type consistency:** `access_token` / `refresh_token` / `token_expires_at` column names used identically across Tasks 3, 4, 5, 6. `_process_fetched_pdf(filename, content, db, email)` signature is introduced in Task 6 (via caller update), referenced by Task 9 tests, then fully re-implemented in Task 9. `PDF_ROOT`, `BACKEND_ROOT`, `build_auth_url`, `exchange_code_for_tokens`, `refresh_access_token` names are consistent across their producer and consumer tasks.
