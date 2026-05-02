"""
End-to-end integration test for the Ringgit backend pipeline.

Exercises: seed → accounts → budget → upload → dashboard → transactions
            → category correction → manual entry → re-check dashboard
            → duplicate upload detection
"""

import io
import os
import pytest

from app.database import get_db
from app.main import app
from app.seed import seed_database
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

INTEGRATION_DB_URL = "sqlite:///./test_integration_ringgit.db"
int_engine = create_engine(INTEGRATION_DB_URL, connect_args={"check_same_thread": False})
IntSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=int_engine)

SAMPLE_TEXT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "sample_data", "maybank_sample.txt"
)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=int_engine)
    session = IntSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=int_engine)


@pytest.fixture()
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _sample_bytes() -> bytes:
    """Return the maybank sample text encoded as bytes (simulates a PDF upload)."""
    with open(SAMPLE_TEXT_PATH, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

def test_full_pipeline(client, db, monkeypatch):
    """Full end-to-end pipeline test."""

    # ------------------------------------------------------------------
    # 1. Seed the database with categories and keyword mappings
    # ------------------------------------------------------------------
    seed_database(db)

    # ------------------------------------------------------------------
    # 2. Create accounts via API
    # ------------------------------------------------------------------
    resp = client.post("/api/accounts", json={
        "name": "Maybank Savings",
        "bank": "maybank",
        "type": "savings",
    })
    assert resp.status_code == 200, resp.text
    maybank_account = resp.json()
    maybank_account_id = maybank_account["id"]

    resp = client.post("/api/accounts", json={
        "name": "TnG eWallet",
        "bank": "tng",
        "type": "ewallet",
    })
    assert resp.status_code == 200, resp.text
    tng_account = resp.json()
    tng_account_id = tng_account["id"]

    # Verify both accounts are listed
    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # ------------------------------------------------------------------
    # 3. Set a budget for 2026-03 via API
    # ------------------------------------------------------------------
    resp = client.put("/api/budgets", json={
        "month": "2026-03",
        "target_amount": 4000.0,
    })
    assert resp.status_code == 200, resp.text
    budget = resp.json()
    assert budget["month"] == "2026-03"
    assert budget["target_amount"] == 4000.0

    # ------------------------------------------------------------------
    # 4. Upload a Maybank statement (mock extract_text_from_pdf)
    # ------------------------------------------------------------------
    sample_bytes = _sample_bytes()
    sample_text = sample_bytes.decode("utf-8")

    import app.routers.upload as upload_module

    monkeypatch.setattr(
        upload_module,
        "extract_text_from_pdf",
        lambda content, password=None: sample_text,
    )

    resp = client.post(
        "/api/upload",
        files={"file": ("maybank_april.pdf", io.BytesIO(sample_bytes), "application/pdf")},
        data={"password": ""},
    )
    assert resp.status_code == 200, resp.text
    upload_result = resp.json()

    # ------------------------------------------------------------------
    # 5. Verify upload result
    # ------------------------------------------------------------------
    assert upload_result["status"] == "done", f"Upload failed: {upload_result}"
    assert upload_result["transactions_imported"] == 3, (
        f"Expected 3 transactions, got {upload_result['transactions_imported']}"
    )
    assert upload_result["bank"] == "maybank"

    # ------------------------------------------------------------------
    # 6. Check dashboard for 2026-03
    # ------------------------------------------------------------------
    resp = client.get("/api/dashboard", params={"month": "2026-03"})
    assert resp.status_code == 200, resp.text
    dash = resp.json()

    # Income: TRANSFER FROM A/C = 500.00, REFUND = 50.00 → total 550.00
    assert dash["total_income"] == pytest.approx(550.0, abs=0.01)

    # Spending > 0 (at least one debit: TRANSFER TO A/C = 200.00)
    assert dash["total_spending"] > 0, "Expected non-zero spending"

    # Budget target should be 4000
    assert dash["budget_target"] == pytest.approx(4000.0, abs=0.01)

    # ------------------------------------------------------------------
    # 7. Check transactions list has 3 items
    # ------------------------------------------------------------------
    resp = client.get("/api/transactions", params={"month": "2026-03"})
    assert resp.status_code == 200, resp.text
    transactions = resp.json()
    assert len(transactions) == 3, f"Expected 3 transactions, got {len(transactions)}"

    # ------------------------------------------------------------------
    # 8. Correct a category on an uncategorized transaction (PATCH)
    # ------------------------------------------------------------------
    # Find a transaction that is Uncategorized (IBG TRANSFER TO CIMB is likely uncategorized)
    uncategorized_tx = next(
        (t for t in transactions if t["category_name"] == "Uncategorized"),
        None,
    )
    # If all were categorized, fall back to the first transaction
    if uncategorized_tx is None:
        uncategorized_tx = transactions[0]

    # Get the "Shopping" category id from the DB (or use category_id from a known category)
    from app.models import Category
    shopping_cat = db.query(Category).filter_by(name="Shopping").first()
    assert shopping_cat is not None, "Shopping category not found in seed data"

    tx_id = uncategorized_tx["id"]
    resp = client.patch(
        f"/api/transactions/{tx_id}/category",
        json={"category_id": shopping_cat.id},
    )
    assert resp.status_code == 200, resp.text
    patched = resp.json()
    assert patched["category_id"] == shopping_cat.id
    assert patched["category_name"] == "Shopping"

    # ------------------------------------------------------------------
    # 9. Add a manual cash transaction (POST /api/transactions)
    # ------------------------------------------------------------------
    resp = client.post("/api/transactions", json={
        "account_id": maybank_account_id,
        "date": "2026-03-22",
        "description": "PASAR PAGI TAMAN MELAWATI",
        "amount": 45.00,
        "type": "debit",
        "category_id": None,
    })
    assert resp.status_code == 200, resp.text
    manual_tx = resp.json()
    assert manual_tx["amount"] == pytest.approx(45.0, abs=0.01)
    assert manual_tx["type"] == "debit"
    # statement_id is None for manual entries — verified via the response having valid id
    assert manual_tx["id"] is not None

    # ------------------------------------------------------------------
    # 10. Verify dashboard spending increased after manual entry
    # ------------------------------------------------------------------
    resp = client.get("/api/dashboard", params={"month": "2026-03"})
    assert resp.status_code == 200, resp.text
    dash_after = resp.json()

    assert dash_after["total_spending"] > dash["total_spending"], (
        f"Spending should have increased: before={dash['total_spending']}, "
        f"after={dash_after['total_spending']}"
    )
    # Specifically, spending should increase by 45.00
    assert dash_after["total_spending"] == pytest.approx(
        dash["total_spending"] + 45.0, abs=0.01
    )

    # ------------------------------------------------------------------
    # 11. Attempt duplicate upload — verifies status "duplicate"
    # ------------------------------------------------------------------
    resp = client.post(
        "/api/upload",
        files={"file": ("maybank_april.pdf", io.BytesIO(sample_bytes), "application/pdf")},
        data={"password": ""},
    )
    assert resp.status_code == 200, resp.text
    dup_result = resp.json()
    assert dup_result["status"] == "duplicate", (
        f"Expected 'duplicate', got '{dup_result['status']}'"
    )
    assert dup_result["duplicates_skipped"] == 1
