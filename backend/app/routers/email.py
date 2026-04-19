import hashlib
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.database import get_db
from app.models import Account, Category, EmailAccount, Statement, Transaction
from app.schemas import (
    EmailAccountResponse,
    FetchResult,
    UploadResult,
)
from app.services.categorizer import Categorizer
from app.services.gmail_fetcher import GmailFetcher
from app.services.oauth import refresh_access_token
from app.services.parser_registry import ParserRegistry
from app.services.recurring_detector import RecurringDetector
from app.services.transfer_detector import TransferDetector

logger = logging.getLogger(__name__)

router = APIRouter()

ATM_PATTERN = re.compile(
    r"ATM WITHDRAWAL|CASH W/D|ATM W/D|CASH WITHDRAWAL|PENGELUARAN TUNAI",
    re.IGNORECASE,
)

registry = ParserRegistry()

PDF_ROOT = BACKEND_ROOT / "fetched_pdfs"


def _extract_text_from_pdf(content: bytes, password: str | None = None) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=content, filetype="pdf")
    if password:
        doc.authenticate(password)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def _process_fetched_pdf(filename: str, content: bytes, db: Session, email: str) -> UploadResult:
    file_hash = hashlib.sha256(content).hexdigest()

    # Duplicate check first — avoid disk write on repeats.
    existing = db.query(Statement).filter_by(file_hash=file_hash).first()
    if existing:
        return UploadResult(
            filename=filename,
            bank="",
            transactions_imported=0,
            duplicates_skipped=1,
            status="duplicate",
            message="This statement has already been imported.",
        )

    # Extract text (no password for email PDFs).
    try:
        text = _extract_text_from_pdf(content)
    except Exception:
        return UploadResult(
            filename=filename,
            bank="unknown",
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message="Password-protected PDF. Please upload manually with the password.",
        )

    # Detect bank and period up-front so the saved filename is informative.
    parser = registry.detect_bank(text)
    if parser is None:
        bank_id = "unknown"
        period_month = "unknown"
    else:
        bank_id = parser.bank_id
        period_month = parser.extract_period_month(text) or "unknown"

    # Persist the PDF to disk before parsing runs, so a parser crash still
    # leaves the bytes available for inspection via replay_statement.py.
    email_slug = re.sub(r"\W+", "_", email)
    target_dir = PDF_ROOT / email_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{period_month}_{bank_id}_{file_hash[:8]}.pdf"
    target.write_bytes(content)
    file_path_rel = str(target.relative_to(BACKEND_ROOT))

    if parser is None:
        return UploadResult(
            filename=filename,
            bank="unknown",
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message="Could not detect bank from statement.",
        )

    account = db.query(Account).filter_by(bank=bank_id).first()
    if not account:
        return UploadResult(
            filename=filename,
            bank=bank_id,
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message=f"No account found for bank '{bank_id}'. Please create one first.",
        )

    parsed = parser.parse(text)

    stmt = Statement(
        file_hash=file_hash,
        bank=bank_id,
        source="email",
        filename=filename,
        period_month=period_month if period_month != "unknown" else "",
        file_path=file_path_rel,
    )
    db.add(stmt)
    db.flush()

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

    if period_month and period_month != "unknown":
        TransferDetector(db).apply_transfers(period_month)
    RecurringDetector(db).apply_recurring_flags()

    if len(parsed) == 0 and len(text.strip()) > 100:
        logger.warning(
            "parser %s returned 0 transactions for %s (%d chars extracted); sample: %r",
            bank_id, file_path_rel, len(text), text[:200],
        )

    return UploadResult(
        filename=filename,
        bank=bank_id,
        transactions_imported=len(parsed),
        duplicates_skipped=0,
        status="done",
    )


@router.get("/api/email-accounts", response_model=list[EmailAccountResponse])
def list_email_accounts(db: Session = Depends(get_db)):
    accounts = db.query(EmailAccount).all()
    return accounts


@router.delete("/api/email-accounts/{account_id}")
def delete_email_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(EmailAccount).filter_by(id=account_id).first()
    if not account:
        return {"detail": "Not found"}
    db.delete(account)
    db.commit()
    return {"detail": "Deleted"}


_REFRESH_SKEW_SECONDS = 60


def _token_near_expiry(expires_at_iso: str | None) -> bool:
    if not expires_at_iso:
        return True
    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except ValueError:
        return True
    return datetime.utcnow().timestamp() >= expires_at.timestamp() - _REFRESH_SKEW_SECONDS


@router.post("/api/email-accounts/fetch", response_model=list[FetchResult])
def fetch_all_accounts(db: Session = Depends(get_db)):
    accounts = db.query(EmailAccount).all()
    results = []

    for acct in accounts:
        if _token_near_expiry(acct.token_expires_at) and acct.refresh_token:
            refreshed = refresh_access_token(acct.refresh_token)
            acct.access_token = refreshed["access_token"]
            acct.token_expires_at = refreshed["expires_at"]
            db.commit()

        credentials = Credentials(token=acct.access_token)
        fetcher = GmailFetcher(credentials)

        after_date = acct.last_fetched_at[:10] if acct.last_fetched_at else None
        attachments = fetcher.fetch_statements(after_date=after_date)

        processed = []
        for att in attachments:
            result = _process_fetched_pdf(att["filename"], att["content"], db, acct.email)
            processed.append(result)

        acct.last_fetched_at = datetime.utcnow().isoformat()
        db.commit()

        results.append(FetchResult(
            email=acct.email,
            statements_found=len(attachments),
            statements_processed=processed,
        ))

    return results
