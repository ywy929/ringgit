from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Budget
from app.schemas import BudgetCreate, BudgetResponse

router = APIRouter()


@router.get("/api/budgets/{month}", response_model=BudgetResponse | None)
def get_budget(month: str, db: Session = Depends(get_db)):
    return db.query(Budget).filter_by(month=month).first()


@router.put("/api/budgets", response_model=BudgetResponse)
def upsert_budget(payload: BudgetCreate, db: Session = Depends(get_db)):
    budget = db.query(Budget).filter_by(month=payload.month).first()
    if budget:
        budget.target_amount = payload.target_amount
    else:
        budget = Budget(month=payload.month, target_amount=payload.target_amount)
        db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget
