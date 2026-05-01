# TnG Reprocess + Reconciliation Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reconciliation layer that catches silent parser drift on every statement, then reprocess the existing 760 TnG transactions through today's hardened parser and backfill the new flag.

**Architecture:** Two phases — Phase 1 lands schema (`Statement.needs_review`, `Statement.reconciliation_note`) plus a new `app/services/reconciler.py` that uses `Page.find_tables()` as a side-channel against the regex parser; checks are count cross-check, statement-level balance, per-row monotonic. Phase 2 ships two one-shot scripts (`reprocess_tng.py`, `reconcile_existing.py`) that clean up existing data and backfill the flag.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, FastAPI, PyMuPDF (already in `requirements.txt` — `Page.find_tables()` is part of the core API), pytest. Frontend untouched.

**Reference spec:** `docs/superpowers/specs/2026-05-01-tng-reprocess-and-reconciliation-design.md`

---

## File Map

### New files
- `backend/app/services/reconciler.py` — `ReconcileResult` dataclass, three pure check functions, `reconcile_statement()` public entry point
- `backend/tests/test_reconciler.py` — unit tests for the dataclass and check functions, integration test against a real TnG fixture (skip-if-missing)
- `backend/scripts/reprocess_tng.py` — one-shot DB-rewrite for TnG account
- `backend/scripts/reconcile_existing.py` — one-shot backfill of `needs_review` across every Statement

### Modified files
- `backend/app/models.py` — add `Statement.needs_review` + `Statement.reconciliation_note`
- `backend/app/services/parsers/tng.py` — extract module-level `is_credit_type()` helper from `_extract_new_format_tx`; the method calls it
- `backend/app/routers/email.py` — call reconciler at the end of `_process_fetched_pdf` after the existing `db.commit()`
- `backend/app/routers/upload.py` — call reconciler at the end of `upload_statement` after the existing `db.commit()`
- `backend/ringgit.db` — `ALTER TABLE statements ADD COLUMN` for the two new fields (one-off command)

---

## Task 1: Schema additions for needs_review

**Files:**
- Modify: `backend/app/models.py`
- Modify (data migration only): `backend/ringgit.db`

- [ ] **Step 1: Add the two columns to the `Statement` model**

In `backend/app/models.py`, inside the `Statement` class, add after the existing `file_path` line:

```python
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reconciliation_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

- [ ] **Step 2: ALTER TABLE on the existing dev DB**

Run:

```bash
cd backend
./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.begin() as conn:
    cols = [r[1] for r in conn.execute(text('PRAGMA table_info(statements)')).fetchall()]
    if 'needs_review' not in cols:
        conn.execute(text('ALTER TABLE statements ADD COLUMN needs_review BOOLEAN DEFAULT 0'))
        print('added needs_review')
    if 'reconciliation_note' not in cols:
        conn.execute(text('ALTER TABLE statements ADD COLUMN reconciliation_note VARCHAR(500)'))
        print('added reconciliation_note')
"
```

Expected: prints `added needs_review` and `added reconciliation_note` (or nothing on a re-run).

- [ ] **Step 3: Verify columns exist**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, inspect
insp = inspect(create_engine('sqlite:///./ringgit.db'))
cols = [c['name'] for c in insp.get_columns('statements')]
assert 'needs_review' in cols and 'reconciliation_note' in cols
print('schema ok:', cols)
"
```

Expected: `schema ok: [...needs_review, reconciliation_note...]`.

- [ ] **Step 4: Run the full backend test suite to confirm no regressions**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all currently-passing tests still pass; no new failures.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py
git commit -m "refactor(ringgit): add Statement.needs_review and reconciliation_note columns"
```

---

## Task 2: Extract `is_credit_type()` helper from TnG parser

**Files:**
- Modify: `backend/app/services/parsers/tng.py`
- Modify: `backend/tests/test_tng_parser.py` (add test)

- [ ] **Step 1: Write a failing unit test for the new helper**

Append to `backend/tests/test_tng_parser.py`:

```python
from app.services.parsers.tng import is_credit_type


def test_is_credit_type_known_credit_types():
    # Five canonical credit types — including the line-split DUITNOW_RECEI
    # form where chunk[2] alone is the prefix.
    assert is_credit_type("DUITNOW_RECEI") is True
    assert is_credit_type("DUITNOW_RECEIVEFROM") is True
    assert is_credit_type("Receive from Wallet20250916111") is True
    assert is_credit_type("Reload") is True
    assert is_credit_type("Refund") is True
    assert is_credit_type("Cashback") is True


def test_is_credit_type_known_debit_types():
    # All Payment / RFID Payment / DuitNow QR / Transfer / PayDirect / DUITNOW_TRANSFER
    # variants must come back False so credits aren't accidentally flipped.
    assert is_credit_type("Payment") is False
    assert is_credit_type("RFID Payment") is False
    assert is_credit_type("DuitNow QR") is False
    assert is_credit_type("DuitNow QR TNGD 20251102101") is False
    assert is_credit_type("Transfer to Wallet") is False
    assert is_credit_type("PayDirect Payment 20251017101") is False
    assert is_credit_type("DUITNOW_TRANS") is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_tng_parser.py::test_is_credit_type_known_credit_types -v`
Expected: FAIL with `ImportError: cannot import name 'is_credit_type' from 'app.services.parsers.tng'`.

- [ ] **Step 3: Add the module-level helper to `backend/app/services/parsers/tng.py`**

Add this function at the top of the module, right after the constants block (e.g., right after the `_TYPE_REJOIN` tuple):

```python
def is_credit_type(type_text: str) -> bool:
    """Whether a TnG transaction-type string indicates a credit (money in).

    Shared by the parser's per-row classification and the reconciler's
    sign normalization so the two cannot drift apart. Empty / unknown types
    fall through to debit, which is the safer default for accounting.
    """
    if not type_text:
        return False
    upper = type_text.upper().replace(" ", "")
    return (
        upper.startswith("DUITNOW_RECEI")
        or upper.startswith("RECEIVE")
        or upper.startswith("RELOAD")
        or upper.startswith("REFUND")
        or upper.startswith("CASHBACK")
    )
```

- [ ] **Step 4: Replace the inline credit-detection block in `_extract_new_format_tx`**

In the same file, locate the existing block in `_extract_new_format_tx` that looks like:

```python
        type_text = chunk[2] if len(chunk) > 2 else ""
        if len(chunk) > 3 and chunk[2].upper() == "DUITNOW_RECEI":
            type_text = chunk[2] + chunk[3]
        type_upper = type_text.upper().replace(" ", "")
        is_credit = (
            type_upper.startswith("DUITNOW_RECEI")
            or type_upper.startswith("RECEIVE")
            or type_upper.startswith("RELOAD")
            or type_upper.startswith("REFUND")
            or type_upper.startswith("CASHBACK")
        )
        tx_type = "credit" if is_credit else "debit"
```

Replace it with:

```python
        type_text = chunk[2] if len(chunk) > 2 else ""
        if len(chunk) > 3 and chunk[2].upper() == "DUITNOW_RECEI":
            type_text = chunk[2] + chunk[3]
        tx_type = "credit" if is_credit_type(type_text) else "debit"
```

- [ ] **Step 5: Run the new tests AND the full TnG parser test suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_tng_parser.py -v`
Expected: all tests pass, including the two new `test_is_credit_type_*` tests. The existing tests still pass because the behavior is identical.

- [ ] **Step 6: Run the full backend test suite to catch regressions**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/parsers/tng.py backend/tests/test_tng_parser.py
git commit -m "refactor(ringgit): extract is_credit_type helper from tng parser"
```

---

## Task 3: Reconciler dataclass + pure check functions (TDD)

**Files:**
- Create: `backend/app/services/reconciler.py`
- Create: `backend/tests/test_reconciler.py`

- [ ] **Step 1: Write failing unit tests for the dataclass and three checks**

Create `backend/tests/test_reconciler.py`:

```python
from app.services.reconciler import (
    ReconcileResult,
    _check_count,
    _check_statement_balance,
    _check_per_row,
)


def test_reconcile_result_default_construction():
    r = ReconcileResult(ok=True)
    assert r.ok is True
    assert r.note is None
    assert r.checks_run == []


def test_check_count_pass():
    r = _check_count(db_count=10, table_count=10)
    assert r.ok is True


def test_check_count_fail_includes_both_numbers():
    r = _check_count(db_count=10, table_count=11)
    assert r.ok is False
    assert "10" in r.note and "11" in r.note


def test_check_statement_balance_pass():
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.30, "balance": 97.70},
        {"signed_amount":  5.00, "balance": 102.70},
    ]
    # opening = 100.00 - (-1.50) = 101.50
    # sum     = -1.50 + -2.30 + 5.00 = 1.20
    # closing = 102.70
    # 101.50 + 1.20 = 102.70 ✓
    assert _check_statement_balance(rows).ok is True


def test_check_statement_balance_fail():
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.30, "balance": 95.00},  # off
    ]
    r = _check_statement_balance(rows)
    assert r.ok is False
    assert "balance" in r.note.lower()


def test_check_statement_balance_no_data_passes():
    # Offline-only legacy section — every row's balance is None. Skip-pass.
    rows = [{"signed_amount": -1.75, "balance": None}]
    assert _check_statement_balance(rows).ok is True


def test_check_statement_balance_tolerance_001():
    rows = [
        {"signed_amount": -1.50, "balance": 100.005},
        {"signed_amount": -2.30, "balance": 97.71},  # off by 0.005, within 0.01
    ]
    assert _check_statement_balance(rows).ok is True


def test_check_per_row_pass():
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.30, "balance": 97.70},
        {"signed_amount":  5.00, "balance": 102.70},
    ]
    assert _check_per_row(rows).ok is True


def test_check_per_row_fail_at_specific_row():
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.30, "balance": 99.00},  # should be 97.70
    ]
    r = _check_per_row(rows)
    assert r.ok is False
    assert "row 2" in r.note  # 1-indexed


def test_check_per_row_skips_when_balance_missing():
    # Online row, then offline row (no balance), then back to online. The
    # offline row is unverifiable — the check just skips that pair.
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.00, "balance": None},   # offline, skip
        {"signed_amount": -3.00, "balance": 95.00},  # standalone, skip
    ]
    assert _check_per_row(rows).ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.reconciler'`.

- [ ] **Step 3: Create `backend/app/services/reconciler.py` with dataclass + three check functions**

```python
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
from dataclasses import dataclass, field


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
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/reconciler.py backend/tests/test_reconciler.py
git commit -m "feat(ringgit): reconciler dataclass and three pure check functions"
```

---

## Task 4: `reconcile_statement()` public entry — PDF + table extraction

**Files:**
- Modify: `backend/app/services/reconciler.py`
- Modify: `backend/tests/test_reconciler.py` (add integration test)

- [ ] **Step 1: Write a failing integration test against the real TnG annual fixture**

The fixture lives outside the repo (gitignored). We use `_real_pdf_helper.skip_if_no_fixture` (already in the codebase) to skip when absent.

Append to `backend/tests/test_reconciler.py`:

```python
import shutil
from pathlib import Path

import pytest

from app.models import Account, Statement, Transaction
from app.services.parsers.tng import TnGParser
from app.services.reconciler import reconcile_statement


_FIXTURE_NAME = "tng_annual.pdf"
_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "real"
_FIXTURE_PATH = _FIXTURE_DIR / _FIXTURE_NAME
_TNG_PASSWORD = "172895255"  # owner-supplied; matches PDF_PASSWORD_TNG in .env


def _seed_tng_account(db) -> Account:
    acc = Account(name="TnG", bank="tng", type="ewallet")
    db.add(acc)
    db.commit()
    return acc


@pytest.mark.skipif(not _FIXTURE_PATH.exists(), reason=f"real fixture {_FIXTURE_NAME} not present")
def test_reconcile_real_tng_annual_passes(db, monkeypatch, tmp_path):
    # Use the existing find_tables-validated annual statement. With the regex
    # parser's output and the real PDF, all three checks should pass.
    import fitz

    # Stage the fixture into tmp_path so file_path is portable.
    staged = tmp_path / _FIXTURE_NAME
    shutil.copy(_FIXTURE_PATH, staged)
    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)
    monkeypatch.setitem(
        __import__("app.config", fromlist=["SENDER_PASSWORDS"]).SENDER_PASSWORDS,
        "ewallet@tngdigital.com.my",
        _TNG_PASSWORD,
    )

    acc = _seed_tng_account(db)

    # Parse & insert via the same path the reconciler will compare against.
    doc = fitz.open(str(staged))
    if doc.is_encrypted:
        doc.authenticate(_TNG_PASSWORD)
    text = "".join(p.get_text() for p in doc)
    doc.close()
    parser = TnGParser()
    parsed = parser.parse(text)

    stmt = Statement(
        file_hash="annual-test-hash",
        bank="tng",
        source="email",
        filename=_FIXTURE_NAME,
        period_month=parser.extract_period_month(text) or "",
        file_path=_FIXTURE_NAME,  # relative to monkeypatched BACKEND_ROOT
    )
    db.add(stmt)
    db.flush()
    for p in parsed:
        db.add(Transaction(
            statement_id=stmt.id, account_id=acc.id,
            date=p["date"], description=p["description"],
            amount=p["amount"], type=p["type"],
            external_reference=p.get("external_reference"),
        ))
    db.commit()

    result = reconcile_statement(stmt.id, db)
    assert result.ok, f"reconciliation failed: {result.note} (checks_run={result.checks_run})"
    assert "count" in result.checks_run
    assert "statement" in result.checks_run
    assert "per_row" in result.checks_run


def test_reconcile_missing_file_skips_with_note(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)
    acc = _seed_tng_account(db)
    stmt = Statement(
        file_hash="x", bank="tng", source="email",
        filename="gone.pdf", period_month="", file_path="gone.pdf",
    )
    db.add(stmt); db.commit()
    result = reconcile_statement(stmt.id, db)
    assert result.ok is True
    assert "file missing" in (result.note or "")
    assert result.checks_run == []
```

- [ ] **Step 2: Run the new tests — both should fail (function not yet defined)**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v -k "real or missing"`
Expected: FAIL with `ImportError: cannot import name 'reconcile_statement'`.

- [ ] **Step 3: Implement `reconcile_statement()` plus the table-row normalizer**

Append to `backend/app/services/reconciler.py`:

```python
import re
from pathlib import Path

import fitz
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, SENDER_PASSWORDS
from app.models import Statement, Transaction
from app.services.parsers.tng import is_credit_type


# Header cell values to skip when iterating find_tables output.
_HEADER_CELL_VALUES = {
    "Date", "Trans No.", "Transaction No.", "Status", "Transaction",
}

# Format markers — used to dispatch column maps.
_NEW_FORMAT_MARKER = "TNG WALLET TRANSACTION HISTORY"
_LEGACY_FORMAT_MARKER = "Customer Transactions Statement"

_RM_AMOUNT_RE = re.compile(r"^RM(\d+(?:,\d{3})*\.\d{2})$")
_PLAIN_AMOUNT_RE = re.compile(r"^(\d+(?:,\d{3})*\.\d{2})$")
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _parse_amount(cell: str | None, rm_prefix: bool) -> float | None:
    if not cell:
        return None
    stripped = cell.strip().replace("\n", "")
    pattern = _RM_AMOUNT_RE if rm_prefix else _PLAIN_AMOUNT_RE
    m = pattern.match(stripped)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _extract_rows_from_tng_new(doc: "fitz.Document") -> list[dict]:
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
                type_text = (r[2] or "").strip()
                amount = _parse_amount(r[6], rm_prefix=True)
                balance = _parse_amount(r[7], rm_prefix=True)
                if amount is None:
                    continue
                signed = amount if is_credit_type(type_text) else -amount
                rows.append({"signed_amount": signed, "balance": balance})
    return rows


def _extract_rows_from_tng_legacy(doc: "fitz.Document") -> list[dict]:
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


def reconcile_statement(stmt_id: int, db: Session) -> ReconcileResult:
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
    if _NEW_FORMAT_MARKER in text:
        rows = _extract_rows_from_tng_new(doc)
    elif _LEGACY_FORMAT_MARKER in text:
        rows = _extract_rows_from_tng_legacy(doc)
    else:
        doc.close()
        return ReconcileResult(ok=True, note="unknown bank format")
    doc.close()

    db_count = db.query(Transaction).filter_by(statement_id=stmt_id).count()
    checks_run = ["count"]

    r = _check_count(db_count, len(rows))
    if not r.ok:
        return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

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
```

- [ ] **Step 4: Stage the real TnG fixture so the integration test runs**

Run:

```bash
cd backend && mkdir -p tests/fixtures/real && cp fetched_pdfs/aquamagmayeow94_gmail_com/2025-05_tng_c7caa73d.pdf tests/fixtures/real/tng_annual.pdf
```

Expected: silent success. The file is gitignored (per `tests/fixtures/real/` in `.gitignore`) so this is local-only.

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v`
Expected: 11 passed (9 unit + 1 missing-file + 1 real-fixture). If the fixture step was skipped, the real-fixture test will be skipped instead — that's also acceptable.

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/reconciler.py backend/tests/test_reconciler.py
git commit -m "feat(ringgit): reconcile_statement reads pdf via find_tables and runs checks"
```

---

## Task 5: Hook reconciler into the email-fetch path

**Files:**
- Modify: `backend/app/routers/email.py`
- Modify: `backend/tests/test_pdf_backup.py` (add a regression test)

- [ ] **Step 1: Write a failing test that proves the hook fires and flags failures**

Append to `backend/tests/test_pdf_backup.py`:

```python
def test_reconciler_hook_flags_statement_on_failure(db, pdf_root, monkeypatch):
    # Monkeypatch reconcile_statement to return a failure; verify the email
    # router sets needs_review and the note on the Statement row.
    from app.services.reconciler import ReconcileResult
    from app.models import Statement

    def _fake_reconcile(stmt_id, db_arg):
        return ReconcileResult(ok=False, note="test failure", checks_run=["count"])

    monkeypatch.setattr("app.routers.email.reconcile_statement", _fake_reconcile)

    acc = _seed_account(db)

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text):
            return [{"date": "2026-04-01", "description": "X", "amount": 1.0, "type": "debit"}]
        def extract_period_month(self, text): return "2026-04"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="MAYBANK"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "u@g.com")

    stmt = db.query(Statement).first()
    assert stmt.needs_review is True
    assert stmt.reconciliation_note == "test failure"
```

- [ ] **Step 2: Run the test — it must fail (no hook yet)**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_pdf_backup.py::test_reconciler_hook_flags_statement_on_failure -v`
Expected: FAIL with `AttributeError: module 'app.routers.email' has no attribute 'reconcile_statement'`.

- [ ] **Step 3: Add the import + hook in `backend/app/routers/email.py`**

Add to the imports near the top of the file (next to the other `app.services` imports):

```python
from app.services.reconciler import reconcile_statement
```

In `_process_fetched_pdf`, find the existing block in the success branch:

```python
    db.commit()

    if period_month and period_month != "unknown":
        TransferDetector(db).apply_transfers(period_month)
    RecurringDetector(db).apply_recurring_flags()
```

Add the reconciliation call between `db.commit()` and the `if period_month` line:

```python
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
```

- [ ] **Step 4: Run the new test — it must pass now**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_pdf_backup.py::test_reconciler_hook_flags_statement_on_failure -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green. (Other email-router tests should still pass — the reconciler call against the test PDFs returns `ok=True, note="unknown bank format"` for the synthetic test data, which doesn't flag anything.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/email.py backend/tests/test_pdf_backup.py
git commit -m "feat(ringgit): hook reconciler into email-fetch path"
```

---

## Task 6: Hook reconciler into the manual-upload path

**Files:**
- Modify: `backend/app/routers/upload.py`
- Modify: `backend/tests/test_upload_api.py` (add a regression test)

- [ ] **Step 1: Write a failing test mirroring the email-path one, but for /api/upload**

Append to `backend/tests/test_upload_api.py`:

```python
def test_upload_reconciler_hook_flags_failure(client, db, monkeypatch):
    from app.services.reconciler import ReconcileResult

    def _fake_reconcile(stmt_id, db_arg):
        return ReconcileResult(ok=False, note="upload-test failure", checks_run=["count"])

    monkeypatch.setattr("app.routers.upload.reconcile_statement", _fake_reconcile)

    seed_database(db)
    acc = Account(name="Maybank Savings", bank="maybank", type="savings")
    db.add(acc); db.commit()
    import app.routers.upload as upload_mod
    monkeypatch.setattr(upload_mod, "extract_text_from_pdf", lambda content, password: SAMPLE_TEXT)
    response = client.post(
        "/api/upload",
        files={"file": ("maybank.pdf", b"bytes", "application/pdf")},
    )
    assert response.json()["status"] == "done"

    stmt = db.query(Statement).first()
    assert stmt.needs_review is True
    assert stmt.reconciliation_note == "upload-test failure"
```

- [ ] **Step 2: Run the test — it must fail (no hook yet)**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_upload_api.py::test_upload_reconciler_hook_flags_failure -v`
Expected: FAIL with `AttributeError: module 'app.routers.upload' has no attribute 'reconcile_statement'`.

- [ ] **Step 3: Add the import + hook in `backend/app/routers/upload.py`**

Add to the imports near the top of the file:

```python
from app.services.reconciler import reconcile_statement
```

In `upload_statement`, find the success-branch tail:

```python
    db.commit()

    # Run transfer detection
    if period_month:
        detector = TransferDetector(db)
        detector.apply_transfers(period_month)
```

Add the reconciler call between `db.commit()` and the `if period_month` block:

```python
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
```

- [ ] **Step 4: Run the new test — it must pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_upload_api.py::test_upload_reconciler_hook_flags_failure -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/upload.py backend/tests/test_upload_api.py
git commit -m "feat(ringgit): hook reconciler into manual-upload path"
```

---

## Task 7: Reprocess script for TnG

**Files:**
- Create: `backend/scripts/reprocess_tng.py`

- [ ] **Step 1: Create the script**

Create `backend/scripts/reprocess_tng.py`:

```python
"""Re-parse all TnG statements through the current parser, replacing every
existing TnG transaction in-place. Idempotent — running it twice produces
the same end state. Use when the TnG parser ships fixes that should apply
to historical data.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reprocess_tng.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import SENDER_PASSWORDS
from app.models import Account, Category, Statement, Transaction
from app.services.categorizer import Categorizer
from app.services.parser_registry import ParserRegistry
from app.services.recurring_detector import RecurringDetector


def main() -> int:
    engine = create_engine("sqlite:///./ringgit.db")
    db = sessionmaker(bind=engine)()
    registry = ParserRegistry()
    categorizer = Categorizer(db)
    uncat = db.query(Category).filter_by(name="Uncategorized").first()
    tng_account = db.query(Account).filter_by(bank="tng").first()
    if not tng_account:
        print("no TnG account found; aborting"); return 1

    deleted = db.query(Transaction).filter_by(account_id=tng_account.id).delete()
    db.commit()
    print(f"deleted {deleted} existing TnG transactions")

    stmts = db.query(Statement).filter_by(bank="tng").order_by(Statement.id).all()
    print(f"reprocessing {len(stmts)} TnG statements")

    existing_refs: set[str] = set()
    existing_keys: set[tuple] = set()
    inserted = 0
    skipped = 0
    extraction_failures = 0

    for stmt in stmts:
        fp = Path(stmt.file_path)
        text = None
        candidates = [None] + [pw for pw in SENDER_PASSWORDS.values() if pw]
        for password in candidates:
            try:
                doc = fitz.open(str(fp))
                if doc.is_encrypted:
                    if not password:
                        doc.close(); continue
                    if not doc.authenticate(password):
                        doc.close(); continue
                text = "".join(p.get_text() for p in doc)
                doc.close()
                break
            except Exception:
                continue
        if not text or not text.strip():
            extraction_failures += 1
            continue

        parser = registry.detect_bank(text)
        if parser is None or parser.bank_id != "tng":
            continue

        parsed = parser.parse(text)
        period_month = parser.extract_period_month(text) or ""
        if period_month and stmt.period_month != period_month:
            stmt.period_month = period_month

        for p in parsed:
            ref = p.get("external_reference")
            key = (p["date"], p["amount"], p["type"], p["description"])
            if ref and ref in existing_refs:
                skipped += 1; continue
            if not ref and key in existing_keys:
                skipped += 1; continue
            if ref:
                existing_refs.add(ref)
            existing_keys.add(key)
            cat_id = categorizer.categorize(p["description"])
            if cat_id is None and uncat:
                cat_id = uncat.id
            db.add(Transaction(
                statement_id=stmt.id, account_id=tng_account.id,
                date=p["date"], description=p["description"],
                amount=p["amount"], type=p["type"], category_id=cat_id,
                external_reference=ref,
            ))
            inserted += 1
        db.commit()

    print(f"inserted: {inserted}")
    print(f"skipped (dedup): {skipped}")
    print(f"extraction failures: {extraction_failures}")

    RecurringDetector(db).apply_recurring_flags()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the script against the live DB**

Run: `cd backend && ./.venv/Scripts/python.exe scripts/reprocess_tng.py`
Expected: prints `deleted 760 existing TnG transactions`, `reprocessing 32 TnG statements`, `inserted: 760` (plus or minus a handful from parser fixes that previously over-collapsed rows), `skipped (dedup): N`, `extraction failures: 0`.

- [ ] **Step 3: Verify final state**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    total = conn.execute(text(\"SELECT COUNT(*) FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE bank='tng')\")).scalar()
    with_ref = conn.execute(text(\"SELECT COUNT(*) FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE bank='tng') AND external_reference IS NOT NULL\")).scalar()
    print(f'TnG total: {total}, with ref: {with_ref}')
"
```

Expected: `TnG total: ~760, with ref: ~760` (every TnG row gets a ref because every TnG statement format produces one).

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/reprocess_tng.py
git commit -m "feat(ringgit): scripts/reprocess_tng.py to rebuild tng transactions"
```

---

## Task 8: Backfill reconciliation flag across every Statement

**Files:**
- Create: `backend/scripts/reconcile_existing.py`

- [ ] **Step 1: Create the script**

Create `backend/scripts/reconcile_existing.py`:

```python
"""Run the reconciler against every Statement row and persist the result on
the row (needs_review + reconciliation_note). Useful as a backfill after the
reconciler ships, and as an audit pass after parser fixes.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reconcile_existing.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Statement
from app.services.reconciler import reconcile_statement


def main() -> int:
    engine = create_engine("sqlite:///./ringgit.db")
    db = sessionmaker(bind=engine)()

    stmts = db.query(Statement).order_by(Statement.id).all()
    print(f"reconciling {len(stmts)} statements")

    flagged = 0
    skipped_encryption = 0
    skipped_no_file = 0
    skipped_unknown_format = 0
    cleared = 0

    for stmt in stmts:
        result = reconcile_statement(stmt.id, db)
        if not result.ok:
            stmt.needs_review = True
            stmt.reconciliation_note = result.note
            flagged += 1
        else:
            # Skip notes are informational only — clear any prior flag.
            note = (result.note or "").lower()
            if "encrypted" in note:
                skipped_encryption += 1
            elif "file missing" in note:
                skipped_no_file += 1
            elif "unknown" in note:
                skipped_unknown_format += 1
            if stmt.needs_review:
                stmt.needs_review = False
                stmt.reconciliation_note = None
                cleared += 1
        db.commit()

    print(f"flagged needs_review: {flagged}")
    print(f"cleared prior flags: {cleared}")
    print(f"skipped (encryption): {skipped_encryption}")
    print(f"skipped (file missing): {skipped_no_file}")
    print(f"skipped (unknown format): {skipped_unknown_format}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the script**

Run: `cd backend && ./.venv/Scripts/python.exe scripts/reconcile_existing.py`
Expected: prints `reconciling 71 statements` (current Statement count) followed by counts. The flagged count should be small — single digits — for a healthy system.

- [ ] **Step 3: Inspect the flagged statements**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    rows = conn.execute(text('SELECT id, bank, period_month, filename, reconciliation_note FROM statements WHERE needs_review = 1')).fetchall()
    print(f'{len(rows)} flagged:')
    for r in rows:
        print(f'  id={r[0]} bank={r[1]} period={r[2]} file={r[3]} note={r[4]}')
"
```

Expected: zero or small number of rows. Each one is a candidate to investigate manually — open the PDF, eyeball whether the reconciler is right or whether it's a false positive that needs a parser/reconciler fix.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/reconcile_existing.py
git commit -m "feat(ringgit): scripts/reconcile_existing.py to backfill needs_review"
```

---

## Self-review

**Spec coverage:** every section of `2026-05-01-tng-reprocess-and-reconciliation-design.md` has at least one task —
- Schema changes → Task 1.
- `is_credit_type` shared helper (mentioned as a Risks-and-Open-Questions mitigation) → Task 2.
- Reconciler dataclass + three checks → Task 3.
- `reconcile_statement` PDF read + format dispatch + skip semantics → Task 4.
- Hook into `_process_fetched_pdf` → Task 5.
- Hook into `upload_statement` → Task 6.
- Reprocess script → Task 7.
- Backfill reconciliation script → Task 8.
- "Manual smoke after Phase 2" — covered by inline verification commands in Tasks 7 and 8.
- Out-of-scope items (UI surfacing, Maybank/CIMB/etc, LLM fallback) — correctly absent from the plan.

**Placeholder scan:** no TBD/TODO markers; every step has either concrete code or a concrete command with expected output.

**Type consistency:** `ReconcileResult(ok, note, checks_run)` shape used identically across Tasks 3 (definition + unit tests), 4 (returned by `reconcile_statement` + integration tests), 5 and 6 (consumed by routers). `is_credit_type(type_text: str) -> bool` signature consistent across Task 2 (definition + tests), Task 4 (used by both `_extract_rows_from_tng_new` and `_extract_rows_from_tng_legacy`). `Statement.needs_review: bool` and `Statement.reconciliation_note: str | None` names used identically across Tasks 1, 5, 6, 8. Reconciler's `_HEADER_CELL_VALUES`, `_NEW_FORMAT_MARKER`, `_LEGACY_FORMAT_MARKER` constants are defined once in Task 4 and not shadowed elsewhere.
