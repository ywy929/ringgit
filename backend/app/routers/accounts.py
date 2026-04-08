from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account
from app.schemas import AccountCreate, AccountResponse

router = APIRouter()


@router.get("/api/accounts", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)):
    return db.query(Account).all()


@router.post("/api/accounts", response_model=AccountResponse)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    account = Account(name=payload.name, bank=payload.bank, type=payload.type)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(Account).get(account_id)
    if not account:
        return {"detail": "Not found"}
    db.delete(account)
    db.commit()
    return {"detail": "Deleted"}
