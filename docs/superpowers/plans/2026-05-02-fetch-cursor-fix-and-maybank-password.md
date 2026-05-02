# Fetch Cursor Fix + Maybank Password Wire-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `PDF_PASSWORD_MAYBANK` through `SENDER_PASSWORDS`, fix the silent `last_fetched_at` advancement bug that locks out historical emails, ship a reusable `reset_fetch_cursor.py` script, and back-fetch the missed Maybank historical emails on `wengyeowyeap@gmail.com`.

**Architecture:** Three small file changes (config wire-up, conditional cursor advancement in the email router, new CLI script) plus regression tests pinning both cursor branches. After landing, run the new script to reset `wengyeowyeap@gmail.com`'s cursor and re-fetch.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, FastAPI, pytest. No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-05-02-fetch-cursor-fix-and-maybank-password-design.md`

---

## File Map

### Modified files
- `backend/app/config.py` — add Maybank entry to `SENDER_PASSWORDS` dict
- `backend/app/routers/email.py` — wrap `acct.last_fetched_at` advancement in `if attachments:`
- `backend/tests/test_email_fetch_refresh.py` — append two regression tests for cursor branches

### New files
- `backend/scripts/reset_fetch_cursor.py` — CLI: `python scripts/reset_fetch_cursor.py <email>` sets that account's `last_fetched_at` to NULL

### Untouched
- `backend/.env` — user already added `PDF_PASSWORD_MAYBANK`
- `backend/app/services/parsers/` — Maybank parser is out of scope

---

## Task 1: Wire `PDF_PASSWORD_MAYBANK` into `SENDER_PASSWORDS`

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add the Maybank entry to `SENDER_PASSWORDS`**

In `backend/app/config.py`, locate the existing dict:

```python
SENDER_PASSWORDS: dict[str, str | None] = {
    "ewallet@tngdigital.com.my": _pw("PDF_PASSWORD_TNG"),
    "estatement@aeonrewards.com.my": _pw("PDF_PASSWORD_AEON"),
}
```

Add one new line:

```python
SENDER_PASSWORDS: dict[str, str | None] = {
    "ewallet@tngdigital.com.my": _pw("PDF_PASSWORD_TNG"),
    "estatement@aeonrewards.com.my": _pw("PDF_PASSWORD_AEON"),
    "m2u@stmts.maybank2u.com.my": _pw("PDF_PASSWORD_MAYBANK"),
}
```

- [ ] **Step 2: Verify the env var is loaded**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from app.config import SENDER_PASSWORDS
for k, v in SENDER_PASSWORDS.items():
    print(f'  {k}: {\"<set>\" if v else \"<not set>\"}')"
```

Expected: three rows printed, all showing `<set>` (TnG, AEON, Maybank). If the Maybank row shows `<not set>`, the env var `PDF_PASSWORD_MAYBANK` isn't actually in `backend/.env` — pause and confirm with the user before proceeding.

- [ ] **Step 3: Run the full backend test suite to confirm no regressions**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all currently-passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(ringgit): wire PDF_PASSWORD_MAYBANK through SENDER_PASSWORDS"
```

---

## Task 2: Cursor advancement fix (TDD)

**Files:**
- Modify: `backend/app/routers/email.py`
- Modify: `backend/tests/test_email_fetch_refresh.py`

- [ ] **Step 1: Append two failing tests to `backend/tests/test_email_fetch_refresh.py`**

```python
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
```

The test file already imports `EmailAccount`, `_iso`, `_utc_naive_now`, `timedelta`, `patch` from prior tests. Confirm this with: `head -10 backend/tests/test_email_fetch_refresh.py`. If anything's missing add the import.

- [ ] **Step 2: Run the new tests — `test_fetch_does_not_advance_cursor_when_no_attachments` MUST fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_email_fetch_refresh.py::test_fetch_does_not_advance_cursor_when_no_attachments -v`
Expected: FAIL — current code unconditionally advances `last_fetched_at`. The assertion `acct.last_fetched_at == past` fails because the cursor was advanced.

The other new test (`test_fetch_advances_cursor_when_attachments_found`) should PASS with current code, since the existing behavior also advances the cursor when attachments are present.

- [ ] **Step 3: Apply the fix in `backend/app/routers/email.py`**

In `fetch_all_accounts`, locate the existing line that unconditionally advances the cursor:

```python
        acct.last_fetched_at = _utcnow_naive().isoformat()
        db.commit()
```

Wrap the assignment in a conditional. The result should be:

```python
        if attachments:
            acct.last_fetched_at = _utcnow_naive().isoformat()
        db.commit()
```

`db.commit()` stays unconditional because other writes in the loop (token refresh, encrypted-stub creation in `_process_fetched_pdf`) need to land regardless of cursor advancement.

- [ ] **Step 4: Run the new tests — both must pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_email_fetch_refresh.py -v`
Expected: all tests pass, including the two new ones.

- [ ] **Step 5: Run the full backend test suite to confirm no regressions**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/email.py backend/tests/test_email_fetch_refresh.py
git commit -m "fix(ringgit): only advance last_fetched_at when ≥1 attachment processed"
```

---

## Task 3: Reset-cursor CLI script

**Files:**
- Create: `backend/scripts/reset_fetch_cursor.py`

- [ ] **Step 1: Create the script**

Create `backend/scripts/reset_fetch_cursor.py`:

```python
"""Reset an email account's last_fetched_at cursor to NULL so the next
fetch is unbounded (Gmail query without `after:` filter), allowing
historical emails to be re-pulled.

Use when:
- You added a new sender to BANK_SENDERS and want to back-fetch emails
  from that sender that pre-date the account's existing cursor.
- You suspect the cursor was advanced spuriously and missed something.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reset_fetch_cursor.py <email>

Example:
    cd backend && ./.venv/Scripts/python.exe scripts/reset_fetch_cursor.py wengyeowyeap@gmail.com
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import EmailAccount


def main(email: str) -> int:
    engine = create_engine("sqlite:///./ringgit.db")
    db = sessionmaker(bind=engine)()
    acct = db.query(EmailAccount).filter_by(email=email).first()
    if acct is None:
        print(f"no email account found for {email!r}")
        db.close()
        return 1

    prior = acct.last_fetched_at
    acct.last_fetched_at = None
    db.commit()
    print(f"reset cursor for {email}: was {prior!r}, now NULL")
    db.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/reset_fetch_cursor.py <email>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
```

- [ ] **Step 2: Run the script against `wengyeowyeap@gmail.com`**

Run: `cd backend && ./.venv/Scripts/python.exe scripts/reset_fetch_cursor.py wengyeowyeap@gmail.com`
Expected: prints `reset cursor for wengyeowyeap@gmail.com: was '2026-05-01T13:46:03.087813', now NULL` (timestamp value will differ but the format is similar).

- [ ] **Step 3: Verify the cursor is actually NULL**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    rows = conn.execute(text('SELECT email, last_fetched_at FROM email_accounts')).fetchall()
    for r in rows: print(f'  email={r[0]} last_fetched_at={r[1]}')
"
```

Expected: `wengyeowyeap@gmail.com last_fetched_at=None` and `aquamagmayeow94@gmail.com last_fetched_at=<existing timestamp unchanged>`.

- [ ] **Step 4: Test the "no such account" branch**

Run: `cd backend && ./.venv/Scripts/python.exe scripts/reset_fetch_cursor.py nonexistent@example.com`
Expected: prints `no email account found for 'nonexistent@example.com'` and exits with code 1.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/reset_fetch_cursor.py
git commit -m "feat(ringgit): scripts/reset_fetch_cursor.py for back-fetch on new senders"
```

---

## Task 4: Manual smoke — re-fetch and verify Maybank lands

**Files:**
- None modified

This task is verification-only. Validates that Tasks 1–3 together produce the expected outcome end-to-end.

- [ ] **Step 1: Restart the backend so config reloads `SENDER_PASSWORDS` from `.env`**

The backend reads `.env` at module import. If the backend process is currently running and was started before `PDF_PASSWORD_MAYBANK` was added to `.env`, restart it. Procedure depends on how the user is running it; in this session's pattern, the controller manages a background `uvicorn` process — kill and restart.

If no backend is running, skip this step. The next manual fetch from the UI will start with fresh config.

- [ ] **Step 2: User clicks Fetch in the UI**

The user (not the implementer subagent) opens `http://localhost:5173/settings`, clicks **Fetch now**.

Expected via the access log: `POST /api/email-accounts/fetch HTTP/1.1 200 OK`. No new ERROR/WARNING lines (in particular, no `auth_failed` for the Maybank password).

- [ ] **Step 3: Verify Maybank PDFs landed**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
import os
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    n = conn.execute(text(\"SELECT COUNT(*) FROM statements WHERE filename LIKE '%maybank%' OR filename LIKE '847673614_%'\")).scalar()
    print(f'Statements matching Maybank-shaped filenames: {n}')
    n2 = conn.execute(text(\"SELECT COUNT(*) FROM statements WHERE file_path LIKE '%wengyeowyeap%'\")).scalar()
    print(f'Statements with file_path under wengyeowyeap_gmail_com: {n2}')
print()
print('files in fetched_pdfs/wengyeowyeap_gmail_com/:')
d = 'fetched_pdfs/wengyeowyeap_gmail_com'
if os.path.isdir(d):
    for f in sorted(os.listdir(d))[:10]:
        print(f'  {f}')
else:
    print('  (directory does not exist)')
"
```

Expected: at least one Maybank-shaped statement (filename pattern `<digits>_<YYYYMMDD>_<digits>.pdf`) shows up under the `wengyeowyeap_gmail_com/` directory. The exact count depends on how many historical Maybank emails exist in that inbox.

- [ ] **Step 4: Verify the reconciler doesn't barf on Maybank**

The Maybank statements will be `bank='unknown'` (no Maybank parser yet — out of scope). The reconciler should treat them as `note="unknown bank format"` and not flag them. Confirm:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    rows = conn.execute(text(\"SELECT filename, bank, needs_review FROM statements WHERE file_path LIKE '%wengyeowyeap%'\")).fetchall()
    for r in rows: print(f'  file={r[0]} bank={r[1]} needs_review={r[2]}')
"
```

Expected: `bank='unknown'` for each, `needs_review=0` (False).

- [ ] **Step 5: No commit**

This task is verification-only. No code changed.

If Maybank PDFs DID NOT land (Step 3 returns 0):
- Check whether the fetch was actually triggered (look at access log for the `POST /api/email-accounts/fetch`).
- Check whether the gmail account is still authenticated (`auth_failed` status in the response).
- Check whether the Maybank email actually exists in the user's `wengyeowyeap@gmail.com` inbox (the user can verify in Gmail directly).

If the password is wrong (visible as a `ValueError: PDF password authentication failed` in backend logs), the `_process_fetched_pdf` encrypted-stub fallback will save the bytes as `bank='encrypted'` and the user can iterate on the password.

---

## Self-review

**Spec coverage:** every section of `2026-05-02-fetch-cursor-fix-and-maybank-password-design.md` is covered:
- `SENDER_PASSWORDS` Maybank entry → Task 1.
- Cursor advancement fix → Task 2 (TDD with two regression tests).
- `reset_fetch_cursor.py` → Task 3 (creation, run against the wengyeowyeap account, "no such account" branch verification).
- Manual smoke after deploy → Task 4.
- Out-of-scope items (Maybank parser, per-sender cursors, two-cursor model, auto-detect-on-startup) → correctly absent.

**Placeholder scan:** no TBD/TODO; every code step has the actual code, every command step has the exact command and expected output. The "If Maybank PDFs DID NOT land" troubleshooting block in Task 4 is genuine fallback guidance, not a placeholder.

**Type consistency:**
- `EmailAccount.last_fetched_at: str | None` shape used identically across Tasks 2 (test asserts string equality with `past`) and 3 (script sets to `None` and prints `prior!r`).
- `_iso()` and `_utc_naive_now()` helpers reused from existing test file imports — Task 2 confirms via `head -10` check.
- `attachments` local variable name in `fetch_all_accounts` matches the existing variable, so the conditional change is a one-line wrap.
- `SENDER_PASSWORDS` dict shape (`str → str | None`) consistent with prior entries; `_pw()` helper already returns `None` for missing env vars.
