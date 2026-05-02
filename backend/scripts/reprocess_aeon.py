"""Re-parse all AEON Big Card (BC) statements through the current parser,
replacing every existing AEON transaction in-place. Idempotent — running it
twice produces the same end state. Use after AEON parser fixes.

VP prepaid statements are deliberately NOT processed — they remain as
bank='unknown' stubs (per the design decision in the spec).

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reprocess_aeon.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import SENDER_PASSWORDS
from app.models import Account, Category, Statement, Transaction
from app.services.categorizer import Categorizer
from app.services.parser_registry import ParserRegistry
from app.services.recurring_detector import RecurringDetector


def main() -> int:
    engine = create_engine("sqlite:///./ringgit.db")
    db = sessionmaker(bind=engine)()
    registry = ParserRegistry()
    categorizer = Categorizer(db)
    uncat = db.query(Category).filter_by(name="Uncategorized").first()
    aeon_account = db.query(Account).filter_by(bank="aeon").first()
    if not aeon_account:
        print("no AEON account found; aborting"); return 1

    # Step 1: delete existing AEON transactions (none today, but defensive
    # against re-runs after parser fixes).
    deleted = db.query(Transaction).filter_by(account_id=aeon_account.id).delete()
    db.commit()
    print(f"deleted {deleted} existing AEON transactions")

    # Step 2: find candidate BC statements.
    stmts = (
        db.query(Statement)
        .filter(Statement.bank.in_(["unknown", "aeon"]))
        .filter(Statement.filename.like("%BC_STMT%"))
        .order_by(Statement.id)
        .all()
    )
    print(f"reprocessing {len(stmts)} AEON BC statements")

    existing_keys: set[tuple] = set()
    inserted = 0
    skipped = 0
    extraction_failures = 0
    detection_failures = 0

    for stmt in stmts:
        fp = Path(stmt.file_path)
        text = None
        candidates = [None] + [pw for pw in SENDER_PASSWORDS.values() if pw]
        for password in candidates:
            try:
                doc = fitz.open(str(fp))
                if doc.is_encrypted:
                    if not password:
                        doc.close(); continue
                    if not doc.authenticate(password):
                        doc.close(); continue
                text = "".join(p.get_text() for p in doc)
                doc.close()
                break
            except Exception:
                continue
        if not text or not text.strip():
            extraction_failures += 1
            continue

        parser = registry.detect_bank(text)
        if parser is None or parser.bank_id != "aeon":
            detection_failures += 1
            continue

        parsed = parser.parse(text)
        period_month = parser.extract_period_month(text) or ""
        if period_month and stmt.period_month != period_month:
            stmt.period_month = period_month
        # Promote the unknown stub to an aeon-classified statement.
        if stmt.bank != "aeon":
            stmt.bank = "aeon"

        for p in parsed:
            # No external_reference for AEON; broad-key dedup only.
            key = (p["date"], p["amount"], p["type"], p["description"])
            if key in existing_keys:
                skipped += 1; continue
            existing_keys.add(key)
            cat_id = categorizer.categorize(p["description"])
            if cat_id is None and uncat:
                cat_id = uncat.id
            db.add(Transaction(
                statement_id=stmt.id, account_id=aeon_account.id,
                date=p["date"], description=p["description"],
                amount=p["amount"], type=p["type"], category_id=cat_id,
            ))
            inserted += 1
        db.commit()

    print(f"inserted: {inserted}")
    print(f"skipped (dedup): {skipped}")
    print(f"extraction failures: {extraction_failures}")
    print(f"detection failures: {detection_failures}")

    RecurringDetector(db).apply_recurring_flags()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
