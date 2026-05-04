"""Re-parse all Public Bank Moneyplus statements through the current parser,
replacing every existing Public Bank transaction in-place. Idempotent —
running it twice produces the same end state. Use after Public Bank parser
fixes, or as the canonical first-time-account-creation step.

Candidate statements: bank in ('unknown', 'public_bank') AND filename
matches the user's Public Bank pattern. Each candidate is content-confirmed
by `PublicBankParser.can_parse(text)` before being processed.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reprocess_public_bank.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from app.config import BACKEND_ROOT
from app.models import Account, Category, Statement, Transaction
from app.services.categorizer import Categorizer
from app.services.parsers.public_bank import PublicBankParser
from app.services.reconciler import reconcile_statement
from app.services.recurring_detector import RecurringDetector


def main() -> int:
    from app.routers.email import ATM_PATTERN

    engine = create_engine("sqlite:///./ringgit.db")
    db = sessionmaker(bind=engine)()
    parser = PublicBankParser()
    categorizer = Categorizer(db)
    uncat = db.query(Category).filter_by(name="Uncategorized").first()

    # Step 1: ensure the public_bank account exists.
    pb_account = db.query(Account).filter_by(bank="public_bank").first()
    if not pb_account:
        pb_account = Account(
            name="Public Bank Moneyplus",
            bank="public_bank",
            type="bank",
            account_number="public-bank-savings",
        )
        db.add(pb_account); db.commit()
        print(f"created Public Bank account id={pb_account.id}")

    # Step 2: delete existing Public Bank transactions (defensive against re-runs).
    deleted = db.query(Transaction).filter_by(account_id=pb_account.id).delete()
    db.commit()
    print(f"deleted {deleted} existing Public Bank transactions")

    # Step 3: find candidate statements via filename heuristic + bank field.
    stmts = (
        db.query(Statement)
        .filter(Statement.bank.in_(["unknown", "public_bank"]))
        .filter(or_(
            Statement.filename.ilike("%public bank%"),
            Statement.filename.ilike("%public_bank%"),
            Statement.filename.ilike("%moneyplus%"),
        ))
        .order_by(Statement.id)
        .all()
    )
    print(f"reprocessing {len(stmts)} Public Bank candidate statements")

    inserted_total = 0
    extraction_failures = 0
    detection_failures = 0
    reconcile_failures = 0

    for stmt in stmts:
        if not stmt.file_path:
            print(f"  stmt {stmt.id}: no file_path, skipping")
            extraction_failures += 1
            continue
        fp = BACKEND_ROOT / stmt.file_path
        if not fp.exists():
            print(f"  stmt {stmt.id}: file missing at {fp}, skipping")
            extraction_failures += 1
            continue

        try:
            doc = fitz.open(str(fp))
            text = "".join(page.get_text() for page in doc)
            doc.close()
        except Exception as exc:
            print(f"  stmt {stmt.id}: extraction error {exc}, skipping")
            extraction_failures += 1
            continue

        if not parser.can_parse(text):
            print(f"  stmt {stmt.id}: not a Public Bank statement (filename matched, content didn't), skipping")
            detection_failures += 1
            continue

        # Update bank + period_month if the statement was previously 'unknown'.
        if stmt.bank != "public_bank":
            stmt.bank = "public_bank"
        period = parser.extract_period_month(text)
        if period and not stmt.period_month:
            stmt.period_month = period

        parsed = parser.parse(text)

        # No transaction-level dedup — file-level dedup via stmt.file_hash
        # plus this script's DELETE+INSERT covers idempotency. Same-day
        # repeats (toll gates, parking) are real data per ADR-003.
        for p in parsed:
            cat_id = categorizer.categorize(p["description"])
            if cat_id is None and uncat:
                cat_id = uncat.id
            is_atm = bool(ATM_PATTERN.search(p["description"]))
            db.add(Transaction(
                statement_id=stmt.id,
                account_id=pb_account.id,
                date=p["date"],
                description=p["description"],
                amount=p["amount"],
                type=p["type"],
                category_id=cat_id,
                is_cash_withdrawal=is_atm,
            ))
            inserted_total += 1
        db.commit()

        # Reconcile with the new transactions visible.
        rec = reconcile_statement(stmt.id, db)
        if not rec.ok:
            stmt.needs_review = True
            stmt.reconciliation_note = rec.note
            db.commit()
            reconcile_failures += 1
            print(f"  stmt {stmt.id}: parsed {len(parsed)} txs, reconcile FAIL: {rec.note}")
        else:
            stmt.needs_review = False
            stmt.reconciliation_note = None
            db.commit()
            print(f"  stmt {stmt.id}: parsed {len(parsed)} txs, reconcile ok")

    # Step 4: refresh recurring flags account-wide.
    RecurringDetector(db).apply_recurring_flags()

    print()
    print(f"summary: inserted {inserted_total} transactions across {len(stmts)} statements")
    print(f"  extraction failures: {extraction_failures}")
    print(f"  detection failures: {detection_failures}")
    print(f"  reconcile failures: {reconcile_failures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
