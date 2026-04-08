from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Transaction
from app.schemas import TransactionCategoryUpdate, TransactionCreate, TransactionResponse
from app.services.categorizer import Categorizer

router = APIRouter()


@router.get("/api/transactions", response_model=list[TransactionResponse])
def list_transactions(
    month: str | None = Query(None),
    category_id: int | None = Query(None),
    account_id: int | None = Query(None),
    type: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction)

    if month:
        q = q.filter(Transaction.date.like(f"{month}%"))
    if category_id is not None:
        q = q.filter(Transaction.category_id == category_id)
    if account_id is not None:
        q = q.filter(Transaction.account_id == account_id)
    if type:
        q = q.filter(Transaction.type == type)
    if search:
        q = q.filter(Transaction.description.ilike(f"%{search}%"))

    q = q.order_by(Transaction.date.desc(), Transaction.id.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)

    txs = q.all()
    results = []
    for tx in txs:
        cat_name = tx.category.name if tx.category else None
        acc_name = tx.account.name if tx.account else None
        bank = tx.account.bank if tx.account else None
        results.append(TransactionResponse(
            id=tx.id,
            date=tx.date,
            description=tx.description,
            amount=tx.amount,
            type=tx.type,
            category_id=tx.category_id,
            category_name=cat_name,
            account_id=tx.account_id,
            account_name=acc_name,
            bank=bank,
            is_recurring=tx.is_recurring,
            is_cash_withdrawal=tx.is_cash_withdrawal,
            is_internal_transfer=tx.is_internal_transfer,
            linked_transfer_id=tx.linked_transfer_id,
        ))
    return results


@router.post("/api/transactions", response_model=TransactionResponse)
def create_transaction(
    payload: TransactionCreate,
    db: Session = Depends(get_db),
):
    cat_id = payload.category_id
    if cat_id is None:
        categorizer = Categorizer(db)
        cat_id = categorizer.categorize(payload.description)
        if cat_id is None:
            uncat = db.query(Category).filter_by(name="Uncategorized").first()
            cat_id = uncat.id if uncat else None

    tx = Transaction(
        statement_id=None,
        account_id=payload.account_id,
        date=payload.date,
        description=payload.description,
        amount=payload.amount,
        type=payload.type,
        category_id=cat_id,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    cat_name = tx.category.name if tx.category else None
    acc_name = tx.account.name if tx.account else None
    bank = tx.account.bank if tx.account else None
    return TransactionResponse(
        id=tx.id,
        date=tx.date,
        description=tx.description,
        amount=tx.amount,
        type=tx.type,
        category_id=tx.category_id,
        category_name=cat_name,
        account_id=tx.account_id,
        account_name=acc_name,
        bank=bank,
        is_recurring=tx.is_recurring,
        is_cash_withdrawal=tx.is_cash_withdrawal,
        is_internal_transfer=tx.is_internal_transfer,
        linked_transfer_id=tx.linked_transfer_id,
    )


@router.patch("/api/transactions/{tx_id}/category", response_model=TransactionResponse)
def update_transaction_category(
    tx_id: int,
    payload: TransactionCategoryUpdate,
    db: Session = Depends(get_db),
):
    tx = db.query(Transaction).get(tx_id)
    tx.category_id = payload.category_id
    db.commit()
    db.refresh(tx)

    # Learn from user correction
    categorizer = Categorizer(db)
    categorizer.learn(tx.description, payload.category_id)

    cat_name = tx.category.name if tx.category else None
    acc_name = tx.account.name if tx.account else None
    bank = tx.account.bank if tx.account else None
    return TransactionResponse(
        id=tx.id,
        date=tx.date,
        description=tx.description,
        amount=tx.amount,
        type=tx.type,
        category_id=tx.category_id,
        category_name=cat_name,
        account_id=tx.account_id,
        account_name=acc_name,
        bank=bank,
        is_recurring=tx.is_recurring,
        is_cash_withdrawal=tx.is_cash_withdrawal,
        is_internal_transfer=tx.is_internal_transfer,
        linked_transfer_id=tx.linked_transfer_id,
    )
