"""Re-parse all Maybank savings statements through the current parser,
replacing every existing Maybank transaction in-place. Idempotent — running
it twice produces the same end state. Use after Maybank parser fixes.

Candidate statements: bank in ('unknown', 'maybank') AND filename matches
the user's Maybank account suffix `_7244.pdf` OR contains "maybank".
Each candidate is content-confirmed by `MaybankParser.can_parse(text)`
before being processed, so any false-positive filename match is skipped.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reprocess_maybank.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from sqlalchemy import create_engine, or_
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

    # Step 1: ensure the maybank account exists (create if missing — first
    # reprocess is the canonical creation point if fetch hasn't yet).
    maybank_account = db.query(Account).filter_by(bank="maybank").first()
    if not maybank_account:
        maybank_account = Account(
            name="Maybank Savings",
            bank="maybank",
            type="bank",
            account_number="maybank-savings",
        )
        db.add(maybank_account); db.commit()
        print(f"created Maybank account id={maybank_account.id}")

    # Step 2: delete existing Maybank transactions (defensive against re-runs).
    deleted = db.query(Transaction).filter_by(account_id=maybank_account.id).delete()
    db.commit()
    print(f"deleted {deleted} existing Maybank transactions")

    # Step 3: find candidate statements via filename heuristic.
    stmts = (
        db.query(Statement)
        .filter(Statement.bank.in_(["unknown", "maybank"]))
        .filter(or_(
            Statement.filename.like("%_7244.pdf"),
            Statement.filename.like("%maybank%"),
        ))
        .order_by(Statement.id)
        .all()
    )
    print(f"reprocessing {len(stmts)} Maybank candidate statements")

    existing_keys: set[tuple] = set()
    inserted = 0
    skipped = 0
    extraction_failures = 0
    detection_failures = 0

    for stmt in stmts:
        fp = Path(stmt.file_path)
        text = None
        # Try without password first (some PDFs not encrypted), then try every
        # configured password — same as TnG/AEON reprocess scripts.
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

        # Content-confirm via parser registry (rejects false-positive filenames).
        parser = registry.detect_bank(text)
        if parser is None or parser.bank_id != "maybank":
            detection_failures += 1
            continue

        parsed = parser.parse(text)
        period_month = parser.extract_period_month(text) or ""
        if period_month and stmt.period_month != period_month:
            stmt.period_month = period_month
        if stmt.bank != "maybank":
            stmt.bank = "maybank"

        for p in parsed:
            # No external_reference for Maybank; broad-key dedup only.
            key = (p["date"], p["amount"], p["type"], p["description"])
            if key in existing_keys:
                skipped += 1; continue
            existing_keys.add(key)
            cat_id = categorizer.categorize(p["description"])
            if cat_id is None and uncat:
                cat_id = uncat.id
            db.add(Transaction(
                statement_id=stmt.id, account_id=maybank_account.id,
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
