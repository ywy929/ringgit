from app.models import Account, Category, KeywordMapping, Statement, Transaction
from app.seed import seed_database

def _seed_with_transactions(db):
    seed_database(db)
    acc = Account(name="Maybank Savings", bank="maybank", type="savings")
    stmt = Statement(file_hash="h1", bank="maybank", source="manual", filename="s.pdf", period_month="2026-04")
    db.add_all([acc, stmt])
    db.flush()
    food_cat = db.query(Category).filter_by(name="Food & Dining").first()
    uncat = db.query(Category).filter_by(name="Uncategorized").first()
    tx1 = Transaction(statement_id=stmt.id, account_id=acc.id, date="2026-04-07", description="GRABFOOD KL", amount=32.50, type="debit", category_id=food_cat.id)
    tx2 = Transaction(statement_id=stmt.id, account_id=acc.id, date="2026-04-06", description="MYSTERY SHOP", amount=45.00, type="debit", category_id=uncat.id)
    tx3 = Transaction(statement_id=stmt.id, account_id=acc.id, date="2026-04-05", description="SALARY APR", amount=5200.00, type="credit", category_id=db.query(Category).filter_by(name="Income").first().id)
    db.add_all([tx1, tx2, tx3])
    db.commit()
    return tx1, tx2, tx3

def test_list_transactions(client, db):
    _seed_with_transactions(db)
    response = client.get("/api/transactions?month=2026-04")
    assert response.status_code == 200
    assert len(response.json()) == 3

def test_filter_by_category(client, db):
    _seed_with_transactions(db)
    food_cat = db.query(Category).filter_by(name="Food & Dining").first()
    response = client.get(f"/api/transactions?month=2026-04&category_id={food_cat.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["description"] == "GRABFOOD KL"

def test_filter_by_type(client, db):
    _seed_with_transactions(db)
    response = client.get("/api/transactions?month=2026-04&type=credit")
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_update_category_and_learn(client, db):
    tx1, tx2, tx3 = _seed_with_transactions(db)
    fuel_cat = db.query(Category).filter_by(name="Fuel").first()
    response = client.patch(f"/api/transactions/{tx2.id}/category", json={"category_id": fuel_cat.id})
    assert response.status_code == 200
    db.refresh(tx2)
    assert tx2.category_id == fuel_cat.id
    mapping = db.query(KeywordMapping).filter_by(keyword_pattern="MYSTERY SHOP", source="user").first()
    assert mapping is not None
    assert mapping.category_id == fuel_cat.id
