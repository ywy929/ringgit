from pathlib import Path
from app.models import Account, Category, Statement, Transaction
from app.seed import seed_database

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "maybank_sample.txt").read_text()

def test_upload_requires_account(client, db):
    seed_database(db)
    response = client.post("/api/upload", files={"file": ("maybank.pdf", b"dummy", "application/pdf")})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"

def test_upload_and_parse(client, db, monkeypatch):
    seed_database(db)
    acc = Account(name="Maybank Savings", bank="maybank", type="savings")
    db.add(acc)
    db.commit()
    import app.routers.upload as upload_mod
    monkeypatch.setattr(upload_mod, "extract_text_from_pdf", lambda content, password: SAMPLE_TEXT)
    response = client.post("/api/upload", files={"file": ("maybank-apr-2026.pdf", b"fake pdf bytes", "application/pdf")})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "done"
    assert data["bank"] == "maybank"
    assert data["transactions_imported"] == 8
    txs = db.query(Transaction).all()
    assert len(txs) == 8
    salary = [t for t in txs if "SALARY" in t.description][0]
    income_cat = db.query(Category).filter_by(name="Income").first()
    assert salary.category_id == income_cat.id
    atm = [t for t in txs if "ATM" in t.description][0]
    assert atm.is_cash_withdrawal is True

def test_upload_duplicate_rejected(client, db, monkeypatch):
    seed_database(db)
    acc = Account(name="Maybank Savings", bank="maybank", type="savings")
    db.add(acc)
    db.commit()
    import app.routers.upload as upload_mod
    monkeypatch.setattr(upload_mod, "extract_text_from_pdf", lambda content, password: SAMPLE_TEXT)
    pdf_bytes = b"identical pdf content"
    response1 = client.post("/api/upload", files={"file": ("maybank.pdf", pdf_bytes, "application/pdf")})
    assert response1.json()["status"] == "done"
    response2 = client.post("/api/upload", files={"file": ("maybank.pdf", pdf_bytes, "application/pdf")})
    assert response2.json()["status"] == "duplicate"
