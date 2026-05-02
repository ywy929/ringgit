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
