"""Statement reconciliation — runtime guardrail against silent parser drift.

We use PyMuPDF's `Page.find_tables()` as an independent side-channel against
whatever the per-bank regex parser produced. Three checks, each short-circuits:

1. Count cross-check (universal): row counts agree.
2. Statement-level balance (when balance column present): opening + sum == closing.
3. Per-row monotonic (when both adjacent rows have balances): prev + signed == curr.

Failures soft-flag the Statement (caller sets needs_review); inserts are not
rolled back. Skips (encrypted PDFs we cannot open, file missing, unknown bank
format) return ok=True with a note explaining the skip — absence of evidence
is not evidence of failure.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, SENDER_PASSWORDS
from app.models import Statement, Transaction
from app.services.parsers.tng import is_credit_type


@dataclass
class ReconcileResult:
    ok: bool
    note: str | None = None
    checks_run: list[str] = field(default_factory=list)


def _check_count(db_count: int, table_count: int) -> ReconcileResult:
    if db_count != table_count:
        return ReconcileResult(
            ok=False,
            note=f"row count mismatch: db={db_count}, tables={table_count}",
        )
    return ReconcileResult(ok=True)


def _check_statement_balance(rows: list[dict]) -> ReconcileResult:
    balanced = [r for r in rows if r.get("balance") is not None]
    if not balanced:
        return ReconcileResult(ok=True)
    opening = balanced[0]["balance"] - balanced[0]["signed_amount"]
    closing = balanced[-1]["balance"]
    sum_signed = sum(r["signed_amount"] for r in balanced)
    expected = opening + sum_signed
    if abs(expected - closing) > 0.01:
        return ReconcileResult(
            ok=False,
            note=(
                f"closing balance mismatch: opening={opening:.2f}, "
                f"sum={sum_signed:.2f}, expected={closing:.2f}, "
                f"computed={expected:.2f}"
            ),
        )
    return ReconcileResult(ok=True)


def _check_per_row(rows: list[dict]) -> ReconcileResult:
    for i in range(len(rows) - 1):
        prev = rows[i]
        curr = rows[i + 1]
        if prev.get("balance") is None or curr.get("balance") is None:
            continue
        expected = prev["balance"] + curr["signed_amount"]
        if abs(expected - curr["balance"]) > 0.01:
            return ReconcileResult(
                ok=False,
                note=(
                    f"per-row balance mismatch at row {i + 2}: "
                    f"prev={prev['balance']:.2f}, signed_amount={curr['signed_amount']:.2f}, "
                    f"expected={expected:.2f}, got={curr['balance']:.2f}"
                ),
            )
    return ReconcileResult(ok=True)


# ---------------------------------------------------------------------------
# PDF row extraction helpers
# ---------------------------------------------------------------------------

# Header cell values to skip when iterating find_tables output.
_HEADER_CELL_VALUES = {
    "Date", "Trans No.", "Transaction No.", "Status", "Transaction",
}

# Format markers — used to dispatch column maps.
_NEW_FORMAT_MARKER = "TNG WALLET TRANSACTION HISTORY"
_LEGACY_FORMAT_MARKER = "Customer Transactions Statement"
_AEON_MARKER = "AEON CREDIT SERVICE"

_RM_AMOUNT_RE = re.compile(r"^RM(\d+(?:,\d{3})*\.\d{2})$")
_PLAIN_AMOUNT_RE = re.compile(r"^(\d+(?:,\d{3})*\.\d{2})$")
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
# Matches the newline-underscore-newline artifact find_tables inserts when a
# long word is split across a cell boundary (e.g. 'RECEI\n_\nVEFROM').
_CELL_SPLIT_RE = re.compile(r"\n_\n")


def _parse_amount(cell: str | None, rm_prefix: bool) -> float | None:
    if not cell:
        return None
    stripped = cell.strip().replace("\n", "")
    pattern = _RM_AMOUNT_RE if rm_prefix else _PLAIN_AMOUNT_RE
    m = pattern.match(stripped)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _normalize_tng_new_type(cell: str) -> str:
    """Normalize a find_tables type cell to the canonical form is_credit_type expects.

    find_tables may split long tokens across lines with a '\n_\n' joiner
    (e.g. 'DUITNOW RECEI\n_\nVEFROM'). We strip those, collapse whitespace,
    then for DUITNOW* types replace spaces with underscores so is_credit_type's
    'DUITNOW_RECEI' prefix check works correctly.
    """
    t = _CELL_SPLIT_RE.sub("", cell)
    t = " ".join(t.split())
    if t.upper().startswith("DUITNOW"):
        t = t.replace(" ", "_")
    return t


def _extract_rows_from_tng_new(doc: fitz.Document) -> list[dict]:
    # New-format columns: 0=Date 1=Status 2=Type 3=Reference 4=Description
    # 5=Details 6=Amount(RM) 7=Wallet Balance(RM)
    rows: list[dict] = []
    for page in doc:
        for tbl in page.find_tables().tables:
            for r in tbl.extract():
                if not r or len(r) < 8:
                    continue
                first = (r[0] or "").strip()
                if not first or first.split("\n")[0].strip() in _HEADER_CELL_VALUES:
                    continue
                if not _DATE_RE.match(first):
                    continue
                type_text = _normalize_tng_new_type((r[2] or "").strip())
                amount = _parse_amount(r[6], rm_prefix=True)
                balance = _parse_amount(r[7], rm_prefix=True)
                if amount is None:
                    continue
                signed = amount if is_credit_type(type_text) else -amount
                rows.append({"signed_amount": signed, "balance": balance})
    return rows


def _extract_rows_from_tng_legacy(doc: fitz.Document) -> list[dict]:
    # Legacy ONLINE table: 13 cols, type=col[4], amount=col[10], balance=col[11]
    # Legacy OFFLINE table: 11 cols, type=col[4], amount=col[9], balance=None
    rows: list[dict] = []
    for page in doc:
        for tbl in page.find_tables().tables:
            for r in tbl.extract():
                if not r or len(r) < 11:
                    continue
                first = (r[0] or "").strip().split("\n")[0].strip()
                if first in _HEADER_CELL_VALUES:
                    continue
                # Online has 13 cols, offline has 11.
                if len(r) >= 13:
                    type_text = " ".join((r[4] or "").splitlines()).strip()
                    amount = _parse_amount(r[10], rm_prefix=False)
                    balance = _parse_amount(r[11], rm_prefix=False)
                else:
                    type_text = " ".join((r[4] or "").splitlines()).strip()
                    amount = _parse_amount(r[9], rm_prefix=False)
                    balance = None
                if amount is None:
                    continue
                # Legacy uses 'OTA Reload', 'Reload' for credits and 'Fare Usage'
                # for debits — is_credit_type handles "Reload" prefix correctly.
                signed = amount if is_credit_type(type_text) else -amount
                rows.append({"signed_amount": signed, "balance": balance})
    return rows


def _extract_aeon_credit_header_balances(text: str) -> dict | None:
    """Pull Previous Statement Balance and Total Current Balance from the
    bilingual header block. Layout is:

        Credit Card Number / Nombor Kad Kredit
        Previous Statement Balance / Baki Penyata Sebelum
        Total Charges of the Month / Jumlah Caj Bulanan
        Total Current Balance / Jumlah Baki Semasa
        Minimum Payment / Bayaran Minimum
        <16-digit card number>
        RM <previous>
        RM <charges>
        RM <current>
        RM <minimum>

    The 4 RM amounts appear immediately after the card number, in the order
    of the labels above. We anchor on the card-number-then-4-RM-amounts run.
    Returns None if the pattern doesn't match (caller treats as skip).
    """
    m = re.search(
        r"^\d{16}\s*\n"
        r"\s*RM\s*([\d,]+\.\d{2})\s*\n"   # Previous
        r"\s*RM\s*[\d,]+\.\d{2}\s*\n"      # Charges (skipped)
        r"\s*RM\s*([\d,]+\.\d{2})\s*\n"   # Current
        r"\s*RM\s*[\d,]+\.\d{2}",          # Minimum (skipped)
        text,
        re.MULTILINE,
    )
    if not m:
        return None
    return {
        "previous": float(m.group(1).replace(",", "")),
        "current": float(m.group(2).replace(",", "")),
    }


_AEON_DATE_LINE_RE = re.compile(r"^(\d{2})\s+(\w{3})\s+(\d{4})$")
_AEON_AMOUNT_LINE_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$")


def _extract_rows_from_aeon_credit(text: str) -> list[dict]:
    """Same anchor-based walk as AEONParser.parse, but emits {signed_amount,
    balance: None} dicts that the reconciler's check functions consume.

    Sign convention for credit-card statements:
        +amount = debit (purchase / fee — increases balance owed)
        -amount = credit (CR — payment / refund — decreases balance owed)
    """
    lines = [ln.strip() for ln in text.splitlines()]
    anchors: list[int] = []
    for i in range(len(lines) - 1):
        if _AEON_DATE_LINE_RE.match(lines[i]) and _AEON_DATE_LINE_RE.match(lines[i + 1]):
            anchors.append(i)

    rows: list[dict] = []
    for k, start in enumerate(anchors):
        end = anchors[k + 1] if k + 1 < len(anchors) else len(lines)
        chunk = lines[start:end]
        if len(chunk) < 4:
            continue
        # Forward walk for the same reason AEONParser does it: the last-anchor
        # chunk extends to end-of-text past the transactions section, and a
        # backward walk would pick up footer numbers as the amount.
        amount_idx = None
        for j in range(2, len(chunk)):
            if _AEON_AMOUNT_LINE_RE.match(chunk[j]):
                amount_idx = j
                break
        if amount_idx is None:
            continue
        amount = float(chunk[amount_idx].replace(",", ""))
        is_credit = any(ln == "CR" for ln in chunk[2:amount_idx])
        signed = -amount if is_credit else amount
        rows.append({"signed_amount": signed, "balance": None})
    return rows


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def reconcile_statement(stmt_id: int, db: Session) -> ReconcileResult:
    """Open the PDF for stmt_id, extract rows via find_tables, run the three checks."""
    stmt = db.query(Statement).filter_by(id=stmt_id).first()
    if not stmt or not stmt.file_path:
        return ReconcileResult(ok=True, note="no file_path")

    fp = BACKEND_ROOT / stmt.file_path
    if not fp.exists():
        return ReconcileResult(ok=True, note="file missing")

    doc = fitz.open(str(fp))
    if doc.is_encrypted:
        authed = False
        for pw in SENDER_PASSWORDS.values():
            if pw and doc.authenticate(pw):
                authed = True
                break
        if not authed:
            doc.close()
            return ReconcileResult(ok=True, note="encrypted: no configured password")

    text = "".join(p.get_text() for p in doc)
    aeon_headers: dict | None = None
    if _NEW_FORMAT_MARKER in text:
        rows = _extract_rows_from_tng_new(doc)
    elif _LEGACY_FORMAT_MARKER in text:
        rows = _extract_rows_from_tng_legacy(doc)
    elif _AEON_MARKER in text and "Total Charges of the Month" in text:
        rows = _extract_rows_from_aeon_credit(text)
        aeon_headers = _extract_aeon_credit_header_balances(text)
    else:
        doc.close()
        return ReconcileResult(ok=True, note="unknown bank format")
    doc.close()

    db_count = db.query(Transaction).filter_by(statement_id=stmt_id).count()
    checks_run = ["count"]

    r = _check_count(db_count, len(rows))
    if not r.ok:
        return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

    # AEON credit cards have no per-row running balance, so the existing
    # _check_statement_balance can't be used (it requires balance data).
    # Run the inline check using header Previous/Current values.
    if aeon_headers is not None:
        checks_run.append("statement")
        sum_signed = sum(row["signed_amount"] for row in rows)
        expected = aeon_headers["previous"] + sum_signed
        if abs(expected - aeon_headers["current"]) > 0.01:
            return ReconcileResult(
                ok=False,
                note=(
                    f"closing balance mismatch: previous={aeon_headers['previous']:.2f}, "
                    f"sum={sum_signed:.2f}, expected={aeon_headers['current']:.2f}, "
                    f"computed={expected:.2f}"
                ),
                checks_run=checks_run,
            )
        # Per-row check is intentionally skipped — credit card statements
        # don't carry running balances per transaction.
        return ReconcileResult(ok=True, checks_run=checks_run)

    has_balance = any(row.get("balance") is not None for row in rows)
    if has_balance:
        checks_run.append("statement")
        r = _check_statement_balance(rows)
        if not r.ok:
            return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

        checks_run.append("per_row")
        r = _check_per_row(rows)
        if not r.ok:
            return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

    return ReconcileResult(ok=True, checks_run=checks_run)
