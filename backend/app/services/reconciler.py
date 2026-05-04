"""Statement reconciliation — runtime guardrail against silent parser drift.

For each statement we re-extract transaction rows independently of whatever
the per-bank regex parser produced, then cross-check counts and arithmetic.
The extraction strategy is bank-specific: TnG uses PyMuPDF's
`Page.find_tables()`; AEON, Maybank, and Public Bank use anchor-based
text parsing.

Checks (each short-circuits):

1. Count cross-check (universal): row counts agree.
2. Statement-level balance (when balance data is present): opening + sum == closing.
3. Per-row monotonic (when both adjacent rows have balances): prev + signed == curr.

Some banks add inline cross-checks: AEON validates against header Previous /
Current balance values; Maybank validates against explicit BEGINNING and
ENDING balance markers when present; Public Bank validates against the
summary block's closing balance and debit/credit counts.

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
_MAYBANK_MARKER = "Malayan Banking Berhad"
_MAYBANK_MARKER_2 = "URUSNIAGA AKAUN"
_PB_MARKER_1 = "Moneyplus Savings Account"
_PB_MARKER_2 = "Closing Balance In This Statement"

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


_MAYBANK_DATE_LINE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
_MAYBANK_SIGNED_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}[+-]$")
_MAYBANK_BALANCE_RE = re.compile(r"^[\d,]+\.\d{2}$")
# Note: "Malayan Banking Berhad" and "TARIKH PENYATA" are intentionally
# excluded — they appear in the page footer between pages of multi-page
# statements, so using them as end markers would stop extraction early.
_MAYBANK_END_MARKERS = (
    "ENDING BALANCE :",
    "TERMS AND CONDITION",
)


def _extract_maybank_balances(text: str) -> dict | None:
    """Pull BEGINNING BALANCE (always present) and ENDING BALANCE :
    (2018-era only) from a Maybank savings statement.

    BEGINNING BALANCE layout:
        BEGINNING BALANCE
        <amount>

    ENDING BALANCE layout (2018 only):
        ENDING BALANCE :
        <amount>

    Returns dict with keys "beginning" (float) and "ending" (float | None).
    Returns None if BEGINNING BALANCE not found (caller treats as parse failure).
    """
    beg_match = re.search(
        r"BEGINNING BALANCE\s*\n\s*([\d,]+\.\d{2})", text
    )
    if not beg_match:
        return None
    beginning = float(beg_match.group(1).replace(",", ""))

    end_match = re.search(
        r"ENDING BALANCE\s*:\s*\n\s*([\d,]+\.\d{2})", text
    )
    ending: float | None = None
    if end_match:
        ending = float(end_match.group(1).replace(",", ""))

    return {"beginning": beginning, "ending": ending}


# Anchors on the LAST column header "BALANCE\n" of the bilingual block.
# re.search finds the page-1 occurrence whose next 5 lines are pure
# numeric; page-2 repetitions fail to match because they are followed
# by a date line ("24/03"), not an amount.
_PB_SUMMARY_RE = re.compile(
    r"BALANCE\s*\n"
    r"([\d,]+\.\d{2})\s*\n"     # closing
    r"([\d,]+\.\d{2})\s*\n"     # total debits
    r"([\d,]+)\s*\n"            # count debits (allow comma in case >=1000)
    r"([\d,]+\.\d{2})\s*\n"     # total credits
    r"([\d,]+)\s*\n",           # count credits (allow comma in case >=1000)
    re.MULTILINE,
)


def _extract_public_bank_summary(text: str) -> dict | None:
    """Pull the 5-line summary block (closing, total/count debits, total/count
    credits) from a Public Bank Moneyplus statement text. Returns None if
    the block isn't found — caller treats as skip.
    """
    m = _PB_SUMMARY_RE.search(text)
    if not m:
        return None
    return {
        "closing": float(m.group(1).replace(",", "")),
        "total_debits": float(m.group(2).replace(",", "")),
        "count_debits": int(m.group(3).replace(",", "")),
        "total_credits": float(m.group(4).replace(",", "")),
        "count_credits": int(m.group(5).replace(",", "")),
    }


_PB_DATE_LINE_RE = re.compile(r"^\d{2}/\d{2}$")
_PB_NUMBER_LINE_RE = re.compile(r"^[\d,]+\.\d{2}$")
_PB_SECTION_START = "Balance From Last Statement"
_PB_SECTION_END = "Closing Balance In This Statement"
_PB_STRUCTURAL = frozenset({
    "Balance From Last Statement", "Balance B/F", "Balance C/F",
})
_PB_HEADER_LINES = frozenset({
    "TARIKH", "URUS NIAGA", "DEBIT", "KREDIT", "BAKI",
    "DATE", "TRANSACTION", "CREDIT", "BALANCE",
})
_PB_PAGE_FOOTER_RE = re.compile(r"^Muka Surat \d+ Daripada \d+$|^Page \d+ of \d+$")


def _pb_is_noise(line: str) -> bool:
    s = line.strip()
    return s in _PB_HEADER_LINES or bool(_PB_PAGE_FOOTER_RE.match(s))


def _extract_rows_from_public_bank(text: str) -> list[dict]:
    """Independent re-extraction of Public Bank transaction rows for the
    reconciler. Mirrors PublicBankParser.parse — same section bounds, same
    line classifier, same balance-delta sign rule — but emits
    {signed_amount, balance} dicts. The duplicated state-machine logic is
    the cost of the parser-independent reconciler design (ADR-002):
    a regression in the parser must not be masked by the reconciler.
    """
    lines = text.splitlines()

    start = None
    end = len(lines)
    for i, ln in enumerate(lines):
        s = ln.strip()
        if start is None and s == _PB_SECTION_START:
            start = i
        elif s == _PB_SECTION_END:
            end = i
            break
    if start is None or start + 1 >= end:
        return []

    opening_line = lines[start + 1].strip()
    if not _PB_NUMBER_LINE_RE.match(opening_line):
        return []
    prev_balance = float(opening_line.replace(",", ""))

    rows: list[dict] = []
    i = start + 2
    date_seen = False
    while i < end:
        line = lines[i].strip()
        if not line or _pb_is_noise(line) or line in _PB_STRUCTURAL:
            i += 1
            continue
        if _PB_DATE_LINE_RE.match(line):
            date_seen = True
            i += 1
            continue
        if _PB_NUMBER_LINE_RE.match(line):
            if i + 1 >= end:
                break
            next_line = lines[i + 1].strip()
            if not _PB_NUMBER_LINE_RE.match(next_line):
                i += 1
                continue
            if not date_seen:
                # Mirrors PublicBankParser.parse: skip number-pairs that
                # appear before any date line (defensive against malformed
                # statements where the summary block leaks past the section
                # start).
                i += 2
                continue
            curr_balance = float(next_line.replace(",", ""))
            signed = round(curr_balance - prev_balance, 2)
            rows.append({"signed_amount": signed, "balance": curr_balance})
            prev_balance = curr_balance
            # Skip past description lines until next D / N / structural.
            j = i + 2
            while j < end:
                dline = lines[j].strip()
                if not dline:
                    j += 1
                    continue
                if (_PB_DATE_LINE_RE.match(dline) or _PB_NUMBER_LINE_RE.match(dline)
                        or dline in _PB_STRUCTURAL or _pb_is_noise(dline)):
                    break
                j += 1
            i = j
            continue
        i += 1

    return rows


def _extract_rows_from_maybank(text: str) -> list[dict]:
    """Mirror MaybankParser.parse, emit {signed_amount, balance} rows for the
    reconciler.

    Sign convention matches the source's literal sign suffix:
        +amount = credit (incoming money, increases balance)
        -amount = debit  (outgoing money, decreases balance)
    """
    lines = text.splitlines()

    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == "BEGINNING BALANCE":
            start_idx = i + 2
            break
    if start_idx is None:
        return []

    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        stripped = lines[i].strip()
        if any(stripped.startswith(m) for m in _MAYBANK_END_MARKERS):
            end_idx = i
            break

    section = lines[start_idx:end_idx]

    anchors: list[int] = []
    for i, ln in enumerate(section):
        if _MAYBANK_DATE_LINE_RE.match(ln.strip()):
            anchors.append(i)

    rows: list[dict] = []
    for k, start in enumerate(anchors):
        end = anchors[k + 1] if k + 1 < len(anchors) else len(section)
        chunk = section[start:end]
        if len(chunk) < 4:
            continue
        # Walk forward to first signed-amount line.
        signed_idx = None
        for j in range(2, len(chunk)):
            if _MAYBANK_SIGNED_AMOUNT_RE.match(chunk[j].strip()):
                signed_idx = j
                break
        if signed_idx is None:
            continue
        signed_line = chunk[signed_idx].strip()
        sign = signed_line[-1]
        amount = float(signed_line[:-1].replace(",", ""))
        signed = amount if sign == "+" else -amount
        # Balance is the next line.
        if signed_idx + 1 >= len(chunk):
            continue
        balance_line = chunk[signed_idx + 1].strip()
        if not _MAYBANK_BALANCE_RE.match(balance_line):
            continue
        balance = float(balance_line.replace(",", ""))
        rows.append({"signed_amount": signed, "balance": balance})
    return rows


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def reconcile_statement(stmt_id: int, db: Session) -> ReconcileResult:
    """Open the PDF for stmt_id, extract rows via the bank-specific strategy
    (find_tables for TnG, anchor-based text parsing for AEON/Maybank), run the
    three checks plus any bank-specific cross-checks."""
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
    maybank_balances: dict | None = None
    pb_summary: dict | None = None
    if _NEW_FORMAT_MARKER in text:
        rows = _extract_rows_from_tng_new(doc)
    elif _LEGACY_FORMAT_MARKER in text:
        rows = _extract_rows_from_tng_legacy(doc)
    elif _AEON_MARKER in text and "Total Charges of the Month" in text:
        rows = _extract_rows_from_aeon_credit(text)
        aeon_headers = _extract_aeon_credit_header_balances(text)
    elif _MAYBANK_MARKER in text and _MAYBANK_MARKER_2 in text:
        rows = _extract_rows_from_maybank(text)
        maybank_balances = _extract_maybank_balances(text)
    elif _PB_MARKER_1 in text and _PB_MARKER_2 in text:
        rows = _extract_rows_from_public_bank(text)
        pb_summary = _extract_public_bank_summary(text)
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

    # Maybank savings: per-row balance present + explicit BEGINNING BALANCE
    # always + ENDING BALANCE : in 2018-era statements only. Run the existing
    # _check_statement_balance and _check_per_row, then cross-check against
    # the explicit BEGINNING / ENDING values from the header/footer.
    if maybank_balances is not None and rows:
        checks_run.append("statement")
        r = _check_statement_balance(rows)
        if not r.ok:
            return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

        # Cross-check beginning balance: rows[0].balance - rows[0].signed_amount
        # should equal the explicit BEGINNING BALANCE from the statement header.
        derived_beginning = rows[0]["balance"] - rows[0]["signed_amount"]
        if abs(derived_beginning - maybank_balances["beginning"]) > 0.01:
            return ReconcileResult(
                ok=False,
                note=(
                    f"beginning balance mismatch: stated={maybank_balances['beginning']:.2f}, "
                    f"derived={derived_beginning:.2f}"
                ),
                checks_run=checks_run,
            )

        # Cross-check ending balance against rows[-1].balance — only for 2018-era
        # statements that include the explicit ENDING BALANCE : footer line.
        if maybank_balances["ending"] is not None:
            final_balance = rows[-1]["balance"]
            if abs(final_balance - maybank_balances["ending"]) > 0.01:
                return ReconcileResult(
                    ok=False,
                    note=(
                        f"ending balance mismatch: stated={maybank_balances['ending']:.2f}, "
                        f"final_running={final_balance:.2f}"
                    ),
                    checks_run=checks_run,
                )

        checks_run.append("per_row")
        r = _check_per_row(rows)
        if not r.ok:
            return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

        return ReconcileResult(ok=True, checks_run=checks_run)

    # Public Bank Moneyplus: per-row balance always present, plus a 5-line
    # summary block in the statement header that uniquely exposes count
    # data (debits vs credits) — the actually-novel cross-check for this
    # bank. See spec 2026-05-04-public-bank-parser-design.md for rationale.
    if pb_summary is not None and rows:
        checks_run.append("statement")
        r = _check_statement_balance(rows)
        if not r.ok:
            return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

        checks_run.append("per_row")
        r = _check_per_row(rows)
        if not r.ok:
            return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

        # Closing-balance cross-check.
        final_balance = rows[-1]["balance"]
        if abs(final_balance - pb_summary["closing"]) > 0.01:
            return ReconcileResult(
                ok=False,
                note=(
                    f"closing-balance cross-check failed: "
                    f"summary={pb_summary['closing']:.2f}, "
                    f"final_running={final_balance:.2f}"
                ),
                checks_run=checks_run,
            )

        # Count cross-check (genuinely novel for this bank — catches the
        # toll-gate dedup bug shape from ADR-003). Zero-value rows (e.g.,
        # GST DR ... 0.00) are counted as debits to match the bank's own
        # summary, which lists them in the DEBIT column. See the parser's
        # zero-value handling for the rationale.
        db_debits = sum(1 for r in rows if r["signed_amount"] <= 0)
        db_credits = sum(1 for r in rows if r["signed_amount"] > 0)
        if db_debits != pb_summary["count_debits"]:
            return ReconcileResult(
                ok=False,
                note=(
                    f"debit count mismatch: parsed={db_debits}, "
                    f"summary={pb_summary['count_debits']}"
                ),
                checks_run=checks_run,
            )
        if db_credits != pb_summary["count_credits"]:
            return ReconcileResult(
                ok=False,
                note=(
                    f"credit count mismatch: parsed={db_credits}, "
                    f"summary={pb_summary['count_credits']}"
                ),
                checks_run=checks_run,
            )

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
