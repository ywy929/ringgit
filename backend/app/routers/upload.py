import hashlib
import re

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.database import get_db
from app.models import Account, Category, Statement, Transaction
from app.schemas import UploadResult
from app.services.categorizer import Categorizer
from app.services.parser_registry import ParserRegistry
from app.services.reconciler import reconcile_statement
from app.services.recurring_detector import RecurringDetector
from app.services.transfer_detector import TransferDetector

UPLOAD_PDF_ROOT = BACKEND_ROOT / "fetched_pdfs" / "uploads"

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

    # Check for duplicate. An "encrypted" stub means the email-fetch path
    # saved the bytes but couldn't extract text — replace it now that the
    # user is uploading with a password.
    existing = db.query(Statement).filter_by(file_hash=file_hash).first()
    if existing:
        if existing.bank == "encrypted":
            db.delete(existing)
            db.commit()
        else:
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

    # Persist bytes to disk first — so the bytes are recoverable even if no
    # Account exists yet, the parser later changes, or reconciliation needs
    # to re-open the PDF. Mirrors the email-fetch path's behavior.
    period_month = parser.extract_period_month(text) or "unknown"
    UPLOAD_PDF_ROOT.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_PDF_ROOT / f"{period_month}_{bank_id}_{file_hash[:8]}.pdf"
    target.write_bytes(content)
    file_path_rel = str(target.relative_to(BACKEND_ROOT))

    # Find matching account
    account = db.query(Account).filter_by(bank=bank_id).first()
    if not account:
        # Save the Statement with file_path so reprocess scripts can pick it
        # up after the user creates the account (or runs a reprocess script
        # that creates the account itself).
        db.add(Statement(
            file_hash=file_hash,
            bank=bank_id,
            source="upload",
            filename=file.filename or "",
            period_month=period_month if period_month != "unknown" else "",
            file_path=file_path_rel,
        ))
        db.commit()
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

    # Create statement
    stmt = Statement(
        file_hash=file_hash,
        bank=bank_id,
        source="upload",
        filename=file.filename or "",
        period_month=period_month if period_month != "unknown" else "",
        file_path=file_path_rel,
    )
    db.add(stmt)
    db.flush()

    # Categorize and store transactions, with dedup against existing rows in
    # the same account (date, amount, type, description) so an overlapping
    # statement doesn't double-count transactions.
    categorizer = Categorizer(db)
    uncat = db.query(Category).filter_by(name="Uncategorized").first()

    # See _process_fetched_pdf in routers/email.py for the dedup rationale.
    existing_refs: set[str] = set()
    existing_by_key: dict[tuple, list] = {}
    for t in db.query(Transaction).filter_by(account_id=account.id).all():
        if t.external_reference:
            existing_refs.add(t.external_reference)
        existing_by_key.setdefault(
            (t.date, t.amount, t.type, t.description), []
        ).append(t)

    inserted = 0
    skipped = 0
    for p in parsed:
        ref = p.get("external_reference")
        key = (p["date"], p["amount"], p["type"], p["description"])

        if ref and ref in existing_refs:
            skipped += 1
            continue

        if ref:
            ref_less_rows = [t for t in existing_by_key.get(key, []) if t and not t.external_reference]
            if ref_less_rows:
                ref_less_rows[0].external_reference = ref
                existing_refs.add(ref)
                skipped += 1
                continue

        if not ref and key in existing_by_key:
            skipped += 1
            continue

        if ref:
            existing_refs.add(ref)
        existing_by_key.setdefault(key, []).append(None)
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
            external_reference=ref,
        )
        db.add(tx)
        inserted += 1

    db.commit()

    rec = reconcile_statement(stmt.id, db)
    if not rec.ok:
        stmt.needs_review = True
        stmt.reconciliation_note = rec.note
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
        transactions_imported=inserted,
        duplicates_skipped=skipped,
        status="done",
    )
