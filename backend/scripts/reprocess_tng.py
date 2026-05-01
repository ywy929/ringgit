"""Re-parse all TnG statements through the current parser, replacing every
existing TnG transaction in-place. Idempotent — running it twice produces
the same end state. Use when the TnG parser ships fixes that should apply
to historical data.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reprocess_tng.py
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
    tng_account = db.query(Account).filter_by(bank="tng").first()
    if not tng_account:
        print("no TnG account found; aborting")
        return 1

    deleted = db.query(Transaction).filter_by(account_id=tng_account.id).delete()
    db.commit()
    print(f"deleted {deleted} existing TnG transactions")

    stmts = db.query(Statement).filter_by(bank="tng").order_by(Statement.id).all()
    print(f"reprocessing {len(stmts)} TnG statements")

    existing_refs: set[str] = set()
    existing_keys: set[tuple] = set()
    inserted = 0
    skipped = 0
    extraction_failures = 0

    for stmt in stmts:
        fp = Path(stmt.file_path)
        text = None
        candidates = [None] + [pw for pw in SENDER_PASSWORDS.values() if pw]
        for password in candidates:
            try:
                doc = fitz.open(str(fp))
                if doc.is_encrypted:
                    if not password:
                        doc.close()
                        continue
                    if not doc.authenticate(password):
                        doc.close()
                        continue
                text = "".join(p.get_text() for p in doc)
                doc.close()
                break
            except Exception:
                continue
        if not text or not text.strip():
            extraction_failures += 1
            continue

        parser = registry.detect_bank(text)
        if parser is None or parser.bank_id != "tng":
            continue

        parsed = parser.parse(text)
        period_month = parser.extract_period_month(text) or ""
        if period_month and stmt.period_month != period_month:
            stmt.period_month = period_month

        for p in parsed:
            ref = p.get("external_reference")
            key = (p["date"], p["amount"], p["type"], p["description"])
            if ref and ref in existing_refs:
                skipped += 1
                continue
            if not ref and key in existing_keys:
                skipped += 1
                continue
            if ref:
                existing_refs.add(ref)
            existing_keys.add(key)
            cat_id = categorizer.categorize(p["description"])
            if cat_id is None and uncat:
                cat_id = uncat.id
            db.add(Transaction(
                statement_id=stmt.id,
                account_id=tng_account.id,
                date=p["date"],
                description=p["description"],
                amount=p["amount"],
                type=p["type"],
                category_id=cat_id,
                external_reference=ref,
            ))
            inserted += 1
        db.commit()

    print(f"inserted: {inserted}")
    print(f"skipped (dedup): {skipped}")
    print(f"extraction failures: {extraction_failures}")

    RecurringDetector(db).apply_recurring_flags()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
