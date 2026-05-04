"""One-shot loader: POST a list of Public Bank statement PDFs to
/api/upload. The first run uploads all 13 backfill files. Re-runs are
safe — the upload route's file_hash dedup catches duplicates.

The Account row for public_bank must already exist before /api/upload
will insert transactions. If it doesn't, run scripts/reprocess_public_bank.py
afterwards — that script creates the account and re-parses all matching
candidate Statements.

Usage:
    # Default: glob C:/Users/aquam/Downloads/Public Bank *.pdf
    cd backend && ./.venv/Scripts/python.exe scripts/load_public_bank_pdfs.py

    # Explicit file list:
    cd backend && ./.venv/Scripts/python.exe scripts/load_public_bank_pdfs.py path1.pdf path2.pdf
"""
import sys
from glob import glob
from pathlib import Path

import requests

DEFAULT_GLOB = r"C:\Users\aquam\Downloads\Public Bank *.pdf"
UPLOAD_URL = "http://localhost:8000/api/upload"


def main() -> int:
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        paths = [Path(p) for p in glob(DEFAULT_GLOB)]

    if not paths:
        print(f"no PDFs matched (cwd={Path.cwd()}, glob={DEFAULT_GLOB})", file=sys.stderr)
        return 1

    print(f"uploading {len(paths)} files to {UPLOAD_URL}")
    failures = 0
    duplicates = 0
    successes = 0
    failed_no_account = 0

    for path in paths:
        if not path.exists():
            print(f"  {path.name}: MISSING")
            failures += 1
            continue
        with open(path, "rb") as f:
            try:
                resp = requests.post(
                    UPLOAD_URL,
                    files={"file": (path.name, f, "application/pdf")},
                    timeout=60,
                )
            except requests.ConnectionError as exc:
                print(f"  {path.name}: CONNECTION REFUSED — is the backend running at {UPLOAD_URL}? ({exc})")
                failures += 1
                continue
            except requests.RequestException as exc:
                print(f"  {path.name}: REQUEST ERROR {exc}")
                failures += 1
                continue

        if resp.status_code != 200:
            print(f"  {path.name}: HTTP {resp.status_code} — {resp.text[:200]}")
            failures += 1
            continue

        try:
            body = resp.json()
        except Exception:
            print(f"  {path.name}: non-JSON 200 response — {resp.text[:200]}")
            failures += 1
            continue
        status = body.get("status", "?")
        bank = body.get("bank", "?")
        n_imported = body.get("transactions_imported", 0)
        msg = body.get("message", "")
        print(f"  {path.name}: {status} bank={bank} imported={n_imported} — {msg}")

        if status == "duplicate":
            duplicates += 1
        elif status == "failed" and "No account found" in msg:
            failed_no_account += 1
        elif status == "failed":
            failures += 1
        else:
            successes += 1

    print()
    print(f"summary: {successes} succeeded, {duplicates} duplicates, "
          f"{failed_no_account} failed-no-account, {failures} other failures")
    if failed_no_account:
        print()
        print("Some uploads succeeded as Statements but couldn't insert transactions")
        print("because the public_bank Account row doesn't exist yet. Run:")
        print("  ./.venv/Scripts/python.exe scripts/reprocess_public_bank.py")
        print("That script creates the account and re-parses all candidate Statements.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
