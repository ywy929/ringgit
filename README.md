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
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt    # Windows
# source .venv/bin/activate && pip install -r requirements.txt # macOS/Linux
.venv/Scripts/python.exe -m uvicorn app.main:app --reload      # Windows
# uvicorn app.main:app --reload                                # macOS/Linux
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
.venv/Scripts/python.exe scripts/replay_statement.py fetched_pdfs/you_gmail_com/202603_maybank_a1b2c3d4.pdf
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
docs/superpowers/   # specs and plans
```
