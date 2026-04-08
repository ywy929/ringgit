from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Transaction

WINDOW_DAYS = 2


class TransferDetector:
    def __init__(self, db: Session):
        self.db = db

    def detect_transfers(self, month: str) -> list[tuple[int, int]]:
        transactions = (
            self.db.query(Transaction)
            .filter(Transaction.date.like(f"{month}%"))
            .filter(Transaction.is_internal_transfer == False)
            .all()
        )

        debits = [t for t in transactions if t.type == "debit"]
        credits = [t for t in transactions if t.type == "credit"]

        pairs: list[tuple[int, int]] = []
        matched_credit_ids: set[int] = set()

        for d in debits:
            d_date = datetime.strptime(d.date, "%Y-%m-%d")
            for c in credits:
                if c.id in matched_credit_ids:
                    continue
                if c.account_id == d.account_id:
                    continue
                if abs(c.amount - d.amount) > 0.01:
                    continue
                c_date = datetime.strptime(c.date, "%Y-%m-%d")
                if abs((c_date - d_date).days) > WINDOW_DAYS:
                    continue
                pairs.append((d.id, c.id))
                matched_credit_ids.add(c.id)
                break

        return pairs

    def apply_transfers(self, month: str) -> int:
        pairs = self.detect_transfers(month)

        for debit_id, credit_id in pairs:
            debit_tx = self.db.get(Transaction, debit_id)
            credit_tx = self.db.get(Transaction, credit_id)
            debit_tx.is_internal_transfer = True
            credit_tx.is_internal_transfer = True
            debit_tx.linked_transfer_id = credit_id
            credit_tx.linked_transfer_id = debit_id

        self.db.commit()
        return len(pairs)
