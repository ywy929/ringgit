from collections import Counter

from sqlalchemy.orm import Session

from app.models import Transaction

MIN_OCCURRENCES = 3


class RecurringDetector:
    def __init__(self, db: Session):
        self.db = db

    def detect_recurring(self) -> set[str]:
        transactions = self.db.query(Transaction).filter(
            Transaction.type == "debit",
            Transaction.is_internal_transfer == False,
        ).all()

        desc_months: dict[str, set[str]] = {}
        for tx in transactions:
            month = tx.date[:7]
            desc = tx.description.strip().upper()
            if desc not in desc_months:
                desc_months[desc] = set()
            desc_months[desc].add(month)

        return {
            desc for desc, months in desc_months.items()
            if len(months) >= MIN_OCCURRENCES
        }

    def apply_recurring_flags(self) -> int:
        recurring_descs = self.detect_recurring()
        if not recurring_descs:
            return 0

        count = 0
        transactions = self.db.query(Transaction).filter(
            Transaction.type == "debit",
        ).all()

        for tx in transactions:
            if tx.description.strip().upper() in recurring_descs:
                tx.is_recurring = True
                count += 1

        self.db.commit()
        return count
