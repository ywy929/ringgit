from app.models import Account, Statement, Transaction
from app.services.recurring_detector import RecurringDetector


def _setup(db):
    acc = Account(name="Maybank", bank="maybank", type="savings")
    db.add(acc)
    db.flush()

    months = ["2026-01", "2026-02", "2026-03", "2026-04"]
    for i, m in enumerate(months):
        stmt = Statement(file_hash=f"h{i}", bank="maybank", source="manual", filename=f"{m}.pdf", period_month=m)
        db.add(stmt)
        db.flush()

        db.add(Transaction(
            statement_id=stmt.id, account_id=acc.id,
            date=f"{m}-15", description="NETFLIX.COM",
            amount=54.90, type="debit",
        ))
        db.add(Transaction(
            statement_id=stmt.id, account_id=acc.id,
            date=f"{m}-20", description=f"RANDOM SHOP {i}",
            amount=float(50 + i * 10), type="debit",
        ))

    db.commit()
    return acc


def test_detects_recurring(db):
    _setup(db)
    detector = RecurringDetector(db)
    recurring_descs = detector.detect_recurring()
    assert "NETFLIX.COM" in recurring_descs


def test_flags_transactions(db):
    _setup(db)
    detector = RecurringDetector(db)
    count = detector.apply_recurring_flags()
    assert count >= 4

    netflix_txs = db.query(Transaction).filter(
        Transaction.description == "NETFLIX.COM"
    ).all()
    assert all(tx.is_recurring for tx in netflix_txs)
