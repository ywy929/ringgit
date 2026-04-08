from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Budget, Transaction
from app.schemas import CategorySpending, DashboardSummary, TransferSummary

router = APIRouter()


@router.get("/api/dashboard", response_model=DashboardSummary)
def get_dashboard(
    month: str = Query(...),
    db: Session = Depends(get_db),
):
    txs = (
        db.query(Transaction)
        .filter(Transaction.date.like(f"{month}%"))
        .all()
    )

    # Income: credits excluding internal transfers
    total_income = sum(
        t.amount for t in txs
        if t.type == "credit" and not t.is_internal_transfer
    )

    # Spending: debits excluding internal transfers
    total_spending = sum(
        t.amount for t in txs
        if t.type == "debit" and not t.is_internal_transfer
    )

    savings = total_income - total_spending
    savings_pct = (savings / total_income * 100) if total_income > 0 else 0.0

    # Budget
    budget = db.query(Budget).filter_by(month=month).first()
    budget_target = budget.target_amount if budget else None
    budget_used_pct = (total_spending / budget_target * 100) if budget_target else None

    # Category breakdown (debits only, excluding transfers)
    cat_map: dict[int, tuple[str, float]] = {}
    for t in txs:
        if t.type != "debit" or t.is_internal_transfer:
            continue
        cat_id = t.category_id or 0
        cat_name = t.category.name if t.category else "Uncategorized"
        if cat_id in cat_map:
            cat_map[cat_id] = (cat_name, cat_map[cat_id][1] + t.amount)
        else:
            cat_map[cat_id] = (cat_name, t.amount)

    categories = sorted(
        [CategorySpending(category_id=cid, category_name=name, amount=amt) for cid, (name, amt) in cat_map.items()],
        key=lambda c: c.amount,
        reverse=True,
    )

    # Internal transfers (debit side only)
    transfers = []
    for t in txs:
        if t.is_internal_transfer and t.type == "debit" and t.linked_transfer_id:
            from_acc = t.account.name if t.account else "Unknown"
            linked_tx = db.query(Transaction).get(t.linked_transfer_id)
            to_acc = linked_tx.account.name if linked_tx and linked_tx.account else "Unknown"
            transfers.append(TransferSummary(
                from_account=from_acc,
                to_account=to_acc,
                amount=t.amount,
            ))

    # Cash tracking
    cash_withdrawn = sum(t.amount for t in txs if t.is_cash_withdrawal)
    # cash_logged = manual cash transactions (no statement_id, debit)
    cash_logged = sum(
        t.amount for t in txs
        if t.statement_id is None and t.type == "debit"
    )
    cash_untracked = cash_withdrawn - cash_logged

    return DashboardSummary(
        month=month,
        total_income=total_income,
        total_spending=total_spending,
        savings=savings,
        savings_pct=round(savings_pct, 1),
        budget_target=budget_target,
        budget_used_pct=round(budget_used_pct, 1) if budget_used_pct is not None else None,
        cash_withdrawn=cash_withdrawn,
        cash_logged=cash_logged,
        cash_untracked=cash_untracked,
        categories=categories,
        internal_transfers=transfers,
    )
