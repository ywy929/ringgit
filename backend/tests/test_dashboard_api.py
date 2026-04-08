from app.models import Account, Budget, Category, Statement, Transaction
from app.seed import seed_database

def _setup_dashboard_data(db):
    seed_database(db)
    acc = Account(name="Maybank Savings", bank="maybank", type="savings")
    acc2 = Account(name="TnG Wallet", bank="tng", type="ewallet")
    db.add_all([acc, acc2])
    db.flush()
    stmt = Statement(file_hash="h1", bank="maybank", source="manual", filename="s.pdf", period_month="2026-04")
    stmt2 = Statement(file_hash="h2", bank="tng", source="manual", filename="t.pdf", period_month="2026-04")
    db.add_all([stmt, stmt2])
    db.flush()
    income_cat = db.query(Category).filter_by(name="Income").first()
    food_cat = db.query(Category).filter_by(name="Food & Dining").first()
    cash_cat = db.query(Category).filter_by(name="Cash Withdrawal").first()
    transfer_cat = db.query(Category).filter_by(name="Internal Transfer").first()
    db.add(Transaction(statement_id=stmt.id, account_id=acc.id, date="2026-04-01", description="SALARY", amount=5200, type="credit", category_id=income_cat.id))
    db.add(Transaction(statement_id=stmt.id, account_id=acc.id, date="2026-04-03", description="GRABFOOD", amount=32.50, type="debit", category_id=food_cat.id))
    db.add(Transaction(statement_id=stmt.id, account_id=acc.id, date="2026-04-05", description="ATM WITHDRAWAL", amount=200, type="debit", category_id=cash_cat.id, is_cash_withdrawal=True))
    db.add(Transaction(statement_id=stmt.id, account_id=acc.id, date="2026-04-06", description="TNG RELOAD", amount=100, type="debit", category_id=transfer_cat.id, is_internal_transfer=True, linked_transfer_id=5))
    db.add(Transaction(statement_id=stmt2.id, account_id=acc2.id, date="2026-04-06", description="RELOAD FROM MAYBANK", amount=100, type="credit", category_id=transfer_cat.id, is_internal_transfer=True, linked_transfer_id=4))
    db.add(Budget(month="2026-04", target_amount=4000))
    db.commit()

def test_dashboard_summary(client, db):
    _setup_dashboard_data(db)
    response = client.get("/api/dashboard?month=2026-04")
    assert response.status_code == 200
    data = response.json()
    assert data["month"] == "2026-04"
    assert data["total_income"] == 5200.0
    assert data["total_spending"] == 232.50
    assert data["savings"] == 5200.0 - 232.50
    assert data["budget_target"] == 4000.0
    assert data["cash_withdrawn"] == 200.0

def test_dashboard_no_data(client, db):
    seed_database(db)
    response = client.get("/api/dashboard?month=2026-01")
    assert response.status_code == 200
    data = response.json()
    assert data["total_income"] == 0
    assert data["total_spending"] == 0
