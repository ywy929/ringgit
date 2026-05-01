"""Run the reconciler against every Statement row and persist the result on
the row (needs_review + reconciliation_note). Useful as a backfill after the
reconciler ships, and as an audit pass after parser fixes.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reconcile_existing.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Statement
from app.services.reconciler import reconcile_statement


def main() -> int:
    engine = create_engine("sqlite:///./ringgit.db")
    db = sessionmaker(bind=engine)()

    stmts = db.query(Statement).order_by(Statement.id).all()
    print(f"reconciling {len(stmts)} statements")

    flagged = 0
    skipped_encryption = 0
    skipped_no_file = 0
    skipped_unknown_format = 0
    cleared = 0

    for stmt in stmts:
        result = reconcile_statement(stmt.id, db)
        if not result.ok:
            stmt.needs_review = True
            stmt.reconciliation_note = result.note
            flagged += 1
        else:
            # Skip notes are informational only — clear any prior flag.
            note = (result.note or "").lower()
            if "encrypted" in note:
                skipped_encryption += 1
            elif "file missing" in note:
                skipped_no_file += 1
            elif "unknown" in note:
                skipped_unknown_format += 1
            if stmt.needs_review:
                stmt.needs_review = False
                stmt.reconciliation_note = None
                cleared += 1
        db.commit()

    print(f"flagged needs_review: {flagged}")
    print(f"cleared prior flags: {cleared}")
    print(f"skipped (encryption): {skipped_encryption}")
    print(f"skipped (file missing): {skipped_no_file}")
    print(f"skipped (unknown format): {skipped_unknown_format}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
