import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite:///./test_ringgit.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def db():
    Base.metadata.create_all(bind=test_engine)
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def _isolated_pdf_root(tmp_path, monkeypatch):
    # Prevent any test from writing to the real backend/fetched_pdfs/ dir,
    # which holds real bank-statement backups. Both BACKEND_ROOT and PDF_ROOT
    # move together — _process_fetched_pdf uses target.relative_to(BACKEND_ROOT).
    monkeypatch.setattr("app.routers.email.BACKEND_ROOT", tmp_path)
    monkeypatch.setattr("app.routers.email.PDF_ROOT", tmp_path / "fetched_pdfs")


@pytest.fixture
def pdf_root(tmp_path):
    # Tests that need to inspect the isolated PDF dir can request this fixture;
    # it returns the same path the autouse _isolated_pdf_root patched in.
    return tmp_path / "fetched_pdfs"


@pytest.fixture
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
