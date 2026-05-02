# Fetch Cursor Fix + Maybank Password Wire-Up — Design

**Date:** 2026-05-02
**Status:** Approved (pending spec review before plan)
**Goal:** Fix the silent `last_fetched_at` advancement bug that locks out historical emails from senders added after the cursor advanced, wire up the user-supplied `PDF_PASSWORD_MAYBANK` env var into `SENDER_PASSWORDS`, and provide a reusable script to reset a fetch cursor.

## Context

A Maybank historical email (`Savings Account Statement March 2026`, dated 2026-04-26, sender `m2u@stmts.maybank2u.com.my`, password-protected attachment `847673614_20260331_7244.pdf`) was never fetched into the system, despite the sender being in `BANK_SENDERS` since the early-session correction.

Diagnosis: the email is in the user's `wengyeowyeap@gmail.com` account, whose `last_fetched_at` is `2026-05-01T13:46:03`. Subsequent fetches use the Gmail query `after:2026-05-01`, which excludes the Apr 26 email. The cursor was set to that date by an earlier fetch that found 0 results — exactly the failure mode the post-ship corrections section of the original blocking-gaps plan flagged: *"`last_fetched_at` advances even when 0 statements were processed."*

Two compounding causes:

1. **`SENDER_PASSWORDS` is missing a Maybank entry.** The user already added `PDF_PASSWORD_MAYBANK` to `backend/.env`, but the dict in `app/config.py` only maps the TnG and AEON senders. Without the dict entry, the email-fetch path looks up `SENDER_PASSWORDS.get("m2u@stmts.maybank2u.com.my")` and gets `None`, so the password isn't passed to PyMuPDF. The PDF would land as an encrypted-stub regardless of how good the env var is.

2. **`last_fetched_at` advances even on 0-attachment fetches.** When the user connected the second gmail account during the e2e walkthrough, `BANK_SENDERS` was already correct but the Maybank inbox happened to have no emails matching THAT specific window. The cursor still advanced to "now," and the historical Apr 26 email became unreachable from the Gmail query.

The Maybank parser itself is out of scope for this work — that's a separate brainstorm/spec/plan, following the TnG and AEON pattern, kicked off after the historical PDFs land as encrypted-stub or `bank='unknown'` Statement rows.

## Architecture & Phase Sequencing

Single phase, four small changes that land together:

1. Wire `PDF_PASSWORD_MAYBANK` through `SENDER_PASSWORDS` in `app/config.py`.
2. Make `last_fetched_at` advancement conditional on `len(attachments) > 0` in `app/routers/email.py`.
3. New CLI script `backend/scripts/reset_fetch_cursor.py <email>` for the now-and-future use case "I want to back-fetch a specific account's history."
4. Regression tests pinning the new cursor behavior.

After landing: run the reset script for `wengyeowyeap@gmail.com`, restart backend (so `SENDER_PASSWORDS` reloads from env), user clicks Fetch, historical Maybank emails land. They become Statement rows with `bank='unknown'` (no Maybank parser yet) but with the PDF text extracted (the password works), file_path populated, ready for the next brainstorm to convert them to parsed AEON-style data.

## Scope Exclusions

- **Maybank parser.** Out of scope. Separate brainstorm/spec/plan after the historical PDFs land. Today's work just unblocks fetch.
- **Per-sender `last_fetched_at` tracking.** A schema-level change that would fully eliminate the "added new sender" cursor problem without manual reset. Meaningful work, not warranted by current evidence (the manual-reset script suffices for the foreseeable cadence of new-sender additions).
- **Two-cursor model** (`last_attempted` + `last_succeeded`). Same trade-off as above — overengineered for current needs.
- **Auto-detection of "new sender added since last cursor"**, which would auto-reset on backend startup. Too magical; the user will know when they added a sender and can run the script.
- **Refactoring `auth_failed` / `fetch_failed` interaction with the cursor.** Already handled via `FetchResult.status` from prior work; the cursor-advancement fix doesn't need to entangle with it.
- **Resetting the `aquamagmayeow94@gmail.com` cursor.** Per the user's choice — that account's cursor was set after non-empty fetches and we have no evidence of missed senders there. Re-fetching would re-pull all 32 TnG and 31 AEON statements through dedup, adding access-log noise and runtime for no observed benefit.

## Phase 1: Implementation

### `backend/app/config.py`

Add one line to `SENDER_PASSWORDS`:

```python
SENDER_PASSWORDS: dict[str, str | None] = {
    "ewallet@tngdigital.com.my": _pw("PDF_PASSWORD_TNG"),
    "estatement@aeonrewards.com.my": _pw("PDF_PASSWORD_AEON"),
    "m2u@stmts.maybank2u.com.my": _pw("PDF_PASSWORD_MAYBANK"),
}
```

`_pw()` already returns `None` if the env var is unset, so this is safe even if a user hasn't set the Maybank password yet (the Maybank PDF would just go through the existing encrypted-stub path).

### `backend/app/routers/email.py`

In `fetch_all_accounts`, the per-account loop currently runs:

```python
acct.last_fetched_at = _utcnow_naive().isoformat()
db.commit()
```

Change to:

```python
if attachments:
    acct.last_fetched_at = _utcnow_naive().isoformat()
db.commit()
```

`attachments` is the local variable holding `fetcher.fetch_statements(...)`'s return value (already in scope). The `db.commit()` stays unconditional because other parts of the loop (token refresh persistence, encrypted-stub creation in `_process_fetched_pdf`) may have made writes that need to land regardless of cursor advancement.

Edge cases that the new behavior handles correctly:
- Account never produced a result: cursor stays `None`, every fetch is unbounded — historical emails always reachable.
- Account produced ≥1 result in the past, then 0 today: cursor stays at its prior value (today's empty fetch doesn't advance it). On a future non-empty fetch, cursor advances to that day. Correct semantics: "the cursor reflects the latest day on which we actually saw and processed an attachment."
- Account produced ≥1 result today: cursor advances normally. Same as before.

### `backend/scripts/reset_fetch_cursor.py`

New CLI script following the established `scripts/` pattern (`reprocess_tng.py`, `reprocess_aeon.py`, `reconcile_existing.py`).

Signature: `python scripts/reset_fetch_cursor.py <email>`

Behavior:
- Look up the `EmailAccount` row by `email` field.
- If not found: print "no such account" and exit 1.
- Set `last_fetched_at = NULL`, commit.
- Print confirmation.

Idempotent. Re-runnable. The canonical tool for the recurring future scenario "I added a new sender to `BANK_SENDERS` (or fixed something in the search query) and want to back-fetch historical emails on a specific account."

### Tests

Append to `backend/tests/test_email_fetch_refresh.py`:

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

The "advance" test relies on stubbing `_process_fetched_pdf` to avoid the real extraction (which would fail on a junk byte string). The behavior we're verifying is the cursor logic, not the per-PDF processing.

## One-time DB cleanup (after deploy)

Run once after the changes land:

```bash
cd backend && ./.venv/Scripts/python.exe scripts/reset_fetch_cursor.py wengyeowyeap@gmail.com
```

Then restart the backend (config reloads `SENDER_PASSWORDS` from `.env`), and the user clicks Fetch in the UI. Expected outcome: Maybank historical PDFs from `wengyeowyeap@gmail.com` are downloaded, decrypted with `PDF_PASSWORD_MAYBANK`, saved to `fetched_pdfs/wengyeowyeap_gmail_com/`, and recorded as Statement rows with `bank='unknown'` (no Maybank parser exists yet — that's the next brainstorm).

## Testing Strategy Summary

| Phase | Automated | Manual |
|---|---|---|
| 1 | Two new tests in `test_email_fetch_refresh.py` covering both cursor branches. Existing tests still pass. | After deploy + reset + restart: click Fetch in UI, confirm `fetched_pdfs/wengyeowyeap_gmail_com/` is created and contains Maybank PDFs (saved bytes, text extractable via password). Spot-check by counting `SELECT COUNT(*) FROM statements WHERE filename LIKE '%maybank%' OR file_path LIKE '%wengyeowyeap%'` — should be > 0. |

## Risks & Open Questions

- **Cursor never advances if extraction always fails.** With the new conditional, if every fetch returns attachments but `_process_fetched_pdf` consistently fails to extract (no parser, encrypted with wrong password), the cursor still advances because `attachments` is non-empty. That's correct: we DID see the email; we just couldn't parse it. Re-fetching the same emails on every poll would be wasteful, and `file_hash` dedup catches re-attempts anyway.

- **The reset script doesn't re-trigger fetch automatically.** The user must restart the backend (for config reload) and click Fetch in the UI. Could automate via a follow-up `force_refetch` endpoint, but that's UX scope creep — defer.

- **Maybank password format assumption.** The user's email body says the default password is "your Date of Birth in ddMmmYYYY format (e.g. 01Jan1980)." Whatever the user put in `PDF_PASSWORD_MAYBANK` either matches that or matches a custom password they registered on Maybank2u. We can't validate from here — the next fetch will tell us via auth-success or auth-failure.

- **No tracking of "back-fetch needed" state across sender additions.** A future user adds a new sender to `BANK_SENDERS`, forgets to manually reset the cursor, and wonders why historical emails don't appear. Mitigation: README note + commit message on this change should mention the script. A long-term fix is per-sender cursors, deferred.

- **The reset script could be misused** (resetting an account's cursor that didn't need resetting causes a noisy re-fetch). The script prints a confirmation before doing the work; user needs to invoke it explicitly per account. Acceptable trade-off.
