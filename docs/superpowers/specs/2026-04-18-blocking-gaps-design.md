# Ringgit: Resolving Blocking Gaps — Design

**Date:** 2026-04-18
**Status:** Approved (pending spec review before plan)
**Goal:** Make Ringgit usable end-to-end on the author's machine by closing the three gaps that block real use: Gmail OAuth, PDF parser validation against real statements, and developer onboarding.

## Context

The codebase is structurally feature-complete: FastAPI backend with 7 routers and 5 service modules, React frontend with 5 pages, 6 bank parsers, tests for each parser and service. What blocks actual use:

1. **Gmail OAuth is not wired end-to-end.** `POST /api/email-accounts` accepts a raw `oauth_token` string (`backend/app/routers/email.py:163`). There is no consent flow, no refresh-token handling, no `client_id` / `client_secret` configuration. Tokens obtained manually expire in ~1 hour.
2. **Parsers have never seen real PDFs.** Each parser's regexes and column offsets (e.g. `maybank.py:16-18` hardcodes DR=49, CR=63, BAL=77) were tuned against fixtures in `backend/sample_data/*.txt`, not PyMuPDF output from real statements.
3. **No root README.** Only the default Vite template in `frontend/README.md`. A new machine or collaborator has no path from clone to running app.

The author is the sole user, runs the app locally on their own machine, and wants to drive the app by letting two linked Gmail accounts auto-deliver monthly statements.

## Architecture & Phase Sequencing

Three deliverable surfaces, sequenced so each phase validates itself before the next begins:

**Phase 1 — Gmail OAuth.** Backend gains `/api/oauth/start` and `/api/oauth/callback`. Settings page gains a "Connect Gmail" button. `EmailAccount` stores `access_token`, `refresh_token`, `token_expires_at`. `GmailFetcher` refreshes the access token on demand. `client_id` / `client_secret` loaded from `backend/.env` via `python-dotenv`.

**Phase 2 — Fetch + PDF backup.** Every fetched PDF is written to `backend/fetched_pdfs/<email_slug>/<YYYYMM>_<bank>_<hash8>.pdf` before parsing. `Statement.file_path` points at the saved file. `fetched_pdfs/` is gitignored. When a parser returns zero transactions from nonzero text, a warning is logged with the file path.

**Phase 3 — Parser iteration.** A dev script `backend/scripts/replay_statement.py <pdf>` replays any saved PDF through the parser registry and prints detection + parse output. As each bank's parser is validated against a real statement, one regression test per bank is added against a gitignored fixture file.

**Phase 4 — Root README.** `README.md` at repo root covers quickstart, Google Cloud OAuth client creation (one-time), Gmail connection, and the two expected failure modes.

**Dependency chain:** Phase 1 → 2 → 3. Phase 4 is written last (after real setup reveals accurate troubleshooting).

## Scope Exclusions

Deliberately out of scope for this work:

- User authentication / login (app is single-user on local machine)
- Token encryption at rest (SQLite file is on the author's disk; FS is the trust boundary)
- Alembic migrations (no real data yet; schema changes land by dropping `ringgit.db` and re-seeding)
- Retry logic beyond one token refresh attempt
- Parallel Gmail fetches
- Background / scheduled fetches (manual trigger from Settings page is sufficient)

## Phase 1: Gmail OAuth

### Schema changes

`backend/app/models.py` — `EmailAccount`:

| Current column | Change |
|---|---|
| `oauth_token: str` | rename to `access_token: str \| None` |
| — | add `refresh_token: str \| None` |
| — | add `token_expires_at: str \| None` (ISO-8601 UTC) |

Applied by deleting `backend/ringgit.db` and letting `lifespan` recreate + reseed on next backend start. The database contains no real transactions yet.

### Config

Add `python-dotenv==1.0.1` to `backend/requirements.txt`.

New `backend/app/config.py`:
```python
from dotenv import load_dotenv
import os

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/oauth/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
```

New `backend/.env.example` committed to git; real `backend/.env` gitignored.

### New service

`backend/app/services/oauth.py` with three functions:

- `build_auth_url(state: str) -> str` — uses `google_auth_oauthlib.flow.Flow`, scope `https://www.googleapis.com/auth/gmail.readonly`, `access_type="offline"`, `prompt="consent"` (forces Google to return a refresh_token on every consent, not just the first). Returns Google consent URL.
- `exchange_code_for_tokens(code: str) -> dict` — exchanges auth code for tokens. Returns `{email, access_token, refresh_token, expires_at}`. Email is obtained by fetching `https://www.googleapis.com/oauth2/v2/userinfo` with the new access token.
- `refresh_access_token(refresh_token: str) -> dict` — returns `{access_token, expires_at}` by calling Google's token endpoint with `grant_type=refresh_token`.

### Router changes

`backend/app/routers/email.py` (or new `backend/app/routers/oauth.py` mounted at `/api/oauth`):

- `GET /api/oauth/start` — generates cryptographic random `state`, stores in a module-level `dict[str, float]` keyed by state with 10-minute expiry, redirects to `build_auth_url(state)`.
- `GET /api/oauth/callback?code&state` — validates state and TTL, calls `exchange_code_for_tokens`, upserts `EmailAccount` (by email — second call with same email overwrites tokens), responds with an HTTP redirect to `{FRONTEND_URL}/settings?connected={email}`.
- Modify `fetch_all_accounts`: before constructing `Credentials`, if `now_utc() >= token_expires_at - 60s`, call `refresh_access_token`, persist new `access_token` and `token_expires_at`.
- Remove `POST /api/email-accounts` (body-based token entry) and `EmailAccountCreate` schema. OAuth flow becomes the only path to create an account.

### Frontend changes

`frontend/src/pages/Settings.tsx`:

- Replace any "add account by pasting token" UI with a single anchor/button:
  ```tsx
  <a href="http://localhost:8000/api/oauth/start" className="...">Connect Gmail</a>
  ```
- In a `useEffect` on mount: read `new URLSearchParams(location.search).get('connected')`. If present, show a toast ("Connected {email}"), then strip the query param via `history.replaceState`.

### Tests

- `backend/tests/test_oauth_service.py` — mocks Google's token endpoint, verifies:
  - `build_auth_url` contains expected scope, access_type, prompt, state.
  - `exchange_code_for_tokens` parses token response and userinfo correctly.
  - `refresh_access_token` sends refresh_token in body and returns new access_token.
- Existing `test_gmail_fetcher.py` stays; update mock to match new `Credentials` shape if needed.
- Manual e2e: click Connect, authorize account A; click Connect again, authorize account B; verify two `EmailAccount` rows with distinct `refresh_token` values.

## Phase 2: Fetch + PDF Backup

### Schema change

`backend/app/models.py` — `Statement`: add `file_path: str | None = mapped_column(String(500), nullable=True)`.
Nullable because upload-source statements don't need a backup path (user's original file is elsewhere). Applied by same drop-and-reseed.

### Routing logic

Required sequence change inside `_process_fetched_pdf` (`backend/app/routers/email.py`):

1. Compute `file_hash`; run the existing duplicate-hash check — unchanged.
2. Extract text from PDF — unchanged.
3. Detect bank via `registry.detect_bank(text)`.
4. If detection succeeds, call `parser.extract_period_month(text)` (currently invoked later; move it up so filename values are known at write time). If detection fails, use `bank_id = "unknown"` and `period_month = "unknown"`.
5. **Write the PDF to disk** (new step).
6. Call `parser.parse(text)` — if this step throws or returns empty, the bytes are already safe on disk.

Add near the top of `email.py`:
```python
from pathlib import Path
import re

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
PDF_ROOT = BACKEND_ROOT / "fetched_pdfs"
```

Write block (step 5):
```python
email_slug = re.sub(r'\W+', '_', email)
target_dir = PDF_ROOT / email_slug
target_dir.mkdir(parents=True, exist_ok=True)
target = target_dir / f"{period_month or 'unknown'}_{bank_id}_{file_hash[:8]}.pdf"
target.write_bytes(content)
stmt.file_path = str(target.relative_to(BACKEND_ROOT))
```

`_process_fetched_pdf` signature becomes `(filename, content, db, email)` — the owning `email` string is passed in from the `fetch_all_accounts` loop (one extra argument).

### Parser failure visibility

In `_process_fetched_pdf`, after parsing:
```python
if len(parsed) == 0 and len(text.strip()) > 100:
    logger.warning(
        "parser %s returned 0 transactions for %s (%d chars extracted); sample: %r",
        bank_id, target, len(text), text[:200],
    )
```
Use Python's standard `logging` module (`logger = logging.getLogger(__name__)` at the top of `email.py`); no new deps.

### Gitignore

Append to `backend/.gitignore` (create if absent):
```
.env
ringgit.db
fetched_pdfs/
tests/fixtures/real/
```
Also add top-level `.gitignore` entries for `docs/superpowers/specs/*.local.md` if we want personal spec drafts later — optional, defer.

### Tests

- Extend `backend/tests/test_gmail_fetcher.py` (or add `test_pdf_backup.py`): given a mocked Gmail fetch returning one attachment, verify (a) the PDF is written to `fetched_pdfs/<slug>/…`, (b) `Statement.file_path` is populated, (c) a duplicate re-fetch does not overwrite the file (hash-check gate runs first).

## Phase 3: Parser Iteration Tooling

### New dev script

`backend/scripts/replay_statement.py`:

```
$ python scripts/replay_statement.py fetched_pdfs/user_gmail_com/202603_maybank_a1b2c3d4.pdf
bank detected: maybank
period_month: 2026-03
transactions parsed: 14
first 5:
  2026-03-01  SALARY MAR 2026        5200.00  credit
  2026-03-03  GRABFOOD A-32891KL       32.50  debit
  ...
```

Exits 0 if ≥1 transaction parsed, 1 otherwise. No DB access — pure function from PDF path to console output. Reuses `ParserRegistry` and the same PyMuPDF extraction code as `_extract_text_from_pdf`.

### Per-bank regression tests

As each bank's parser is validated against at least one real PDF:

1. Drop the real PDF into `backend/tests/fixtures/real/<bank>_<yyyymm>.pdf` (gitignored).
2. Add `backend/tests/test_<bank>_real.py`:
   ```python
   import pytest, pathlib
   from app.services.parsers.maybank import MaybankParser

   FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "real" / "maybank_202603.pdf"

   @pytest.mark.skipif(not FIXTURE.exists(), reason="real PDF not available")
   def test_maybank_real_pdf_parses_expected_count():
       text = _extract(FIXTURE)
       parser = MaybankParser()
       assert parser.can_parse(text)
       txs = parser.parse(text)
       assert len(txs) == 14  # known transaction count for this statement
       assert txs[0].amount == 5200.00
   ```
3. Guarded with `skipif` so CI (if ever added) and fresh clones pass without the fixtures.

### No upfront parser rewrites

The existing parsers are kept as-is in Phase 3. They are only modified reactively based on what real PDFs reveal when `replay_statement.py` shows a zero-count parse or mis-extracted fields.

## Phase 4: Root README

`README.md` at repo root, structure:

1. **What it is** — two sentences plus link to `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer` for full product docs.
2. **Quickstart** — exact install and run commands for both services, verified working.
3. **Google Cloud setup (one-time)** — six-step walkthrough:
   1. Create a project at `console.cloud.google.com`
   2. Enable Gmail API
   3. Configure OAuth consent screen (External, testing, add yourself as a test user)
   4. Create OAuth client (type: **Web application**)
   5. Add `http://localhost:8000/api/oauth/callback` to authorized redirect URIs
   6. Copy client ID and secret into `backend/.env`
4. **Connecting a Gmail account** — Start both services → Settings → Connect Gmail → repeat for each account.
5. **Troubleshooting** — two entries:
   - *Parser returned 0 transactions:* inspect the saved PDF with `python scripts/replay_statement.py <path>`, fix the bank's regex, rerun the script.
   - *Gmail fetch fails with 401 / token refresh error:* click Connect Gmail for that account again to re-consent.

## Testing Strategy Summary

| Phase | Automated | Manual |
|---|---|---|
| 1 | Unit tests for `oauth.py` service (mocked Google endpoints) | End-to-end Connect flow for both Gmail accounts; verify two distinct refresh tokens stored |
| 2 | Extended `test_gmail_fetcher.py` verifies file writes and `file_path` population | Trigger fetch, confirm PDFs land in `fetched_pdfs/`, confirm dashboard updates |
| 3 | `test_<bank>_real.py` per validated bank (skip-if-missing) | Run `replay_statement.py` per bank; fix regexes reactively |
| 4 | None | Fresh clone walkthrough follows README from zero to connected Gmail |

## Risks & Open Questions

- **Refresh token revocation.** Google may revoke refresh tokens if unused for 6+ months or if the user revokes app access. Mitigation: re-Connect button stays visible; token-refresh failures surface clearly in the fetch endpoint response.
- **`access_type=offline` + `prompt=consent`.** `prompt=consent` is deliberately used so that re-connecting an already-connected account reliably yields a new refresh_token. Without `prompt=consent`, Google returns an access_token but may omit the refresh_token on re-authorization, leaving the DB with a stale refresh_token.
- **OAuth consent screen "unverified app" warning.** Since this is a personal unpublished OAuth client, Google will show a "Google hasn't verified this app" interstitial. Acceptable for single-user local use. README notes this.
- **Real PDF availability.** Phase 3 depends on at least one real PDF per bank arriving via Gmail. If a bank hasn't sent a statement yet, its parser stays unvalidated until one does. This is acceptable — parser iteration is naturally incremental.
