import hashlib
import logging
import re
from datetime import datetime, timezone


def _utcnow_naive() -> datetime:
    # Naive UTC: matches the format produced by _utcnow_iso in models.py and
    # the bias-cancelling .timestamp() comparison in _token_near_expiry.
    return datetime.now(timezone.utc).replace(tzinfo=None)

from fastapi import APIRouter, Depends
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, SENDER_PASSWORDS
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
from app.services.reconciler import reconcile_statement
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
        # authenticate() returns 0 on failure, non-zero on success. Without
        # this guard, a wrong password silently proceeds and page iteration
        # raises a downstream "corrupt object stream" error.
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF password authentication failed")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def _process_fetched_pdf(
    filename: str, content: bytes, db: Session, email: str, sender: str | None = None,
) -> UploadResult:
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

    # Look up password by sender — None if no password configured.
    password = SENDER_PASSWORDS.get(sender) if sender else None

    # Extract text (with password if the sender has one configured).
    try:
        text = _extract_text_from_pdf(content, password=password)
    except Exception:
        # Encrypted/unreadable PDF — save the bytes and record a stub Statement
        # so the dedup gate catches re-fetches. User can decrypt and re-upload
        # via /api/upload with the password; that path replaces this stub.
        email_slug = re.sub(r"\W+", "_", email)
        target_dir = PDF_ROOT / email_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"encrypted_{file_hash[:8]}.pdf"
        target.write_bytes(content)
        file_path_rel = str(target.relative_to(BACKEND_ROOT))
        db.add(Statement(
            file_hash=file_hash,
            bank="encrypted",
            source="email",
            filename=filename,
            period_month="",
            file_path=file_path_rel,
        ))
        db.commit()
        return UploadResult(
            filename=filename,
            bank="unknown",
            transactions_imported=0,
            duplicates_skipped=0,
            status="failed",
            message=f"Password-protected PDF saved to {file_path_rel}. Upload manually with the password.",
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
        # Record the Statement so the file_hash dedup gate catches re-fetches
        # of the same unparseable PDF on subsequent polls. Empty period_month
        # because the schema column is non-null and we have nothing better.
        db.add(Statement(
            file_hash=file_hash,
            bank="unknown",
            source="email",
            filename=filename,
            period_month="",
            file_path=file_path_rel,
        ))
        db.commit()
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
        # Same dedup-on-failure rationale as the unknown-bank branch above.
        db.add(Statement(
            file_hash=file_hash,
            bank=bank_id,
            source="email",
            filename=filename,
            period_month=period_month if period_month != "unknown" else "",
            file_path=file_path_rel,
        ))
        db.commit()
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

    # Three-tier dedup against existing transactions for this account:
    # 1. external_reference (bank-provided per-tx ID): strict, exact match.
    # 2. Promote: new tx HAS a ref, existing row matches broad key but has
    #    no ref — same tx gaining a ref. Update existing instead of insert.
    # 3. Broad (date, amount, type, description): fallback for ref-less parsers.
    #    Two genuinely identical transactions on the same day collapse here.
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
    promoted = 0
    for p in parsed:
        ref = p.get("external_reference")
        key = (p["date"], p["amount"], p["type"], p["description"])

        if ref and ref in existing_refs:
            skipped += 1
            continue

        if ref:
            # Promotion check: a row with the same broad key but no ref is
            # almost certainly the same transaction whose ref wasn't captured
            # before (older parser, missing migration, etc.).
            ref_less_rows = [t for t in existing_by_key.get(key, []) if t and not t.external_reference]
            if ref_less_rows:
                ref_less_rows[0].external_reference = ref
                existing_refs.add(ref)
                promoted += 1
                skipped += 1
                continue

        if not ref and key in existing_by_key:
            skipped += 1
            continue

        if ref:
            existing_refs.add(ref)
        existing_by_key.setdefault(key, []).append(None)  # sentinel — set membership only
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

    # Reconcile against an independent find_tables() pass; soft-flag on failure.
    rec = reconcile_statement(stmt.id, db)
    if not rec.ok:
        stmt.needs_review = True
        stmt.reconciliation_note = rec.note
        db.commit()
        logger.warning("reconcile failed for stmt %d: %s", stmt.id, rec.note)

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
        transactions_imported=inserted,
        duplicates_skipped=skipped,
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
    return _utcnow_naive().timestamp() >= expires_at.timestamp() - _REFRESH_SKEW_SECONDS


@router.post("/api/email-accounts/fetch", response_model=list[FetchResult])
def fetch_all_accounts(db: Session = Depends(get_db)):
    accounts = db.query(EmailAccount).all()
    results = []

    for acct in accounts:
        # Token refresh — most likely failure mode is RefreshError when the
        # refresh_token has been revoked. Surface as auth_failed so the UI
        # can render a Reconnect affordance for this specific account.
        try:
            if _token_near_expiry(acct.token_expires_at) and acct.refresh_token:
                refreshed = refresh_access_token(acct.refresh_token)
                acct.access_token = refreshed["access_token"]
                acct.token_expires_at = refreshed["expires_at"]
                if refreshed.get("refresh_token"):
                    acct.refresh_token = refreshed["refresh_token"]
                db.commit()
        except RefreshError as e:
            logger.warning("token refresh failed for %s: %s", acct.email, e)
            results.append(FetchResult(
                email=acct.email,
                statements_found=0,
                statements_processed=[],
                status="auth_failed",
                error_message=str(e),
            ))
            continue

        # Gmail fetch — network errors, API hiccups, quota issues. Treated as
        # transient (user can retry); does not require re-consent.
        try:
            credentials = Credentials(token=acct.access_token)
            fetcher = GmailFetcher(credentials)
            after_date = acct.last_fetched_at[:10] if acct.last_fetched_at else None
            attachments = fetcher.fetch_statements(after_date=after_date)
        except Exception as e:
            logger.warning("gmail fetch failed for %s: %s", acct.email, e)
            results.append(FetchResult(
                email=acct.email,
                statements_found=0,
                statements_processed=[],
                status="fetch_failed",
                error_message=str(e),
            ))
            continue

        processed = []
        for att in attachments:
            result = _process_fetched_pdf(
                att["filename"], att["content"], db, acct.email,
                sender=att.get("sender"),
            )
            processed.append(result)

        acct.last_fetched_at = _utcnow_naive().isoformat()
        db.commit()

        results.append(FetchResult(
            email=acct.email,
            statements_found=len(attachments),
            statements_processed=processed,
        ))

    return results
