import hashlib
import re

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Category, Statement, Transaction
from app.schemas import UploadResult
from app.services.categorizer import Categorizer
from app.services.parser_registry import ParserRegistry
from app.services.recurring_detector import RecurringDetector
from app.services.transfer_detector import TransferDetector

router = APIRouter()

ATM_PATTERN = re.compile(
    r"ATM WITHDRAWAL|CASH W/D|ATM W/D|CASH WITHDRAWAL|PENGELUARAN TUNAI",
    re.IGNORECASE,
)

registry = ParserRegistry()


def extract_text_from_pdf(content: bytes, password: str | None = None) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=content, filetype="pdf")
    if password:
        doc.authenticate(password)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


@router.post("/api/upload", response_model=UploadResult)
async def upload_statement(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    db: Session = Depends(get_db),
):
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    # Check for duplicate
    existing = db.query(Statement).filter_by(file_hash=file_hash).first()
    if existing:
        return UploadResult(
            filename=file.filename or "",
            bank="",
            transactions_imported=0,
            duplicates_skipped=1,
            status="duplicate",
            message="This statement has already been imported.",
        )

    # Extract text
    try:
        text = extract_text_from_pdf(content, password)
    except Exception:
        return UploadResult(
            filename=file.filename or "",
            bank="unknown",
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message="Could not read PDF file.",
        )

    # Detect bank
    parser = registry.detect_bank(text)
    if not parser:
        return UploadResult(
            filename=file.filename or "",
            bank="unknown",
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message="Could not detect bank from statement.",
        )

    bank_id = parser.bank_id

    # Find matching account
    account = db.query(Account).filter_by(bank=bank_id).first()
    if not account:
        return UploadResult(
            filename=file.filename or "",
            bank=bank_id,
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message=f"No account found for bank '{bank_id}'. Please create one first.",
        )

    # Parse transactions
    parsed = parser.parse(text)
    period_month = parser.extract_period_month(text)

    # Create statement
    stmt = Statement(
        file_hash=file_hash,
        bank=bank_id,
        source="upload",
        filename=file.filename or "",
        period_month=period_month,
    )
    db.add(stmt)
    db.flush()

    # Categorize and store transactions
    categorizer = Categorizer(db)
    uncat = db.query(Category).filter_by(name="Uncategorized").first()

    for p in parsed:
        cat_id = categorizer.categorize(p["description"])
        if cat_id is None and uncat:
            cat_id = uncat.id

        is_atm = bool(ATM_PATTERN.search(p["description"]))

        tx = Transaction(
            statement_id=stmt.id,
            account_id=account.id,
            date=p["date"],
            description=p["description"],
            amount=p["amount"],
            type=p["type"],
            category_id=cat_id,
            is_cash_withdrawal=is_atm,
        )
        db.add(tx)

    db.commit()

    # Run transfer detection
    if period_month:
        detector = TransferDetector(db)
        detector.apply_transfers(period_month)

    # Run recurring transaction detection
    RecurringDetector(db).apply_recurring_flags()

    return UploadResult(
        filename=file.filename or "",
        bank=bank_id,
        transactions_imported=len(parsed),
        duplicates_skipped=0,
        status="done",
    )
