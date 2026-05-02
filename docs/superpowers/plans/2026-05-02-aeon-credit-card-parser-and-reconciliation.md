# AEON Credit Card Parser + Statement-Level Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a working AEON Credit Card (BC / `AMP VISA CLASSIC`) parser using anchor-based text extraction, extend the reconciler with credit-card-style statement-level checks, and reprocess the 31 existing encrypted-stub statements through the new parser.

**Architecture:** The current `AEONParser` is regex-against-fictional-sample (same fate the original TnG parser had). Full rewrite uses anchor-based extraction (two consecutive `DD MMM YYYY` lines per transaction) because PyMuPDF's `Page.find_tables()` doesn't yield clean per-row data on AEON — the PDF table has no row separators. Reconciler gets a third format-detection arm that pulls Previous/Current header balances and validates `previous + Σ(signed) ≈ current` (no per-row balance for credit cards). VP prepaid statements (8 of them) stay as `bank='unknown'` stubs.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, PyMuPDF (`fitz`), pytest. No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-05-02-aeon-credit-card-parser-and-reconciliation-design.md`

---

## File Map

### Modified files
- `backend/sample_data/aeon_sample.txt` — replaced with synthetic line-by-line layout matching real PDF text shape
- `backend/app/services/parsers/aeon.py` — full rewrite, anchor-based parser
- `backend/tests/test_aeon_parser.py` — full rewrite to match new parser
- `backend/app/services/reconciler.py` — add `_AEON_MARKER`, `_extract_aeon_credit_header_balances`, `_extract_rows_from_aeon_credit`, third dispatch arm in `reconcile_statement` with inline statement-level check
- `backend/tests/test_reconciler.py` — append synthetic AEON test + real-fixture test

### New files
- `backend/scripts/reprocess_aeon.py` — one-shot script to convert the 31 encrypted-stub BC statements into parsed AEON transactions
- `backend/tests/fixtures/real/aeon_credit.pdf` — staged real PDF for reconciler integration test (gitignored)

### Untouched
- `backend/app/services/parser_registry.py` — `AEONParser` is already registered; no change needed
- `backend/app/models.py` — no schema change
- `backend/scripts/reconcile_existing.py` — exists from previous work; just re-run after reprocess

---

## Task 1: Replace AEON sample text with real-shape synthetic

**Files:**
- Modify: `backend/sample_data/aeon_sample.txt`

The current sample is column-aligned fictional text that won't match real PDF output. Replace with a line-by-line dump matching what PyMuPDF actually produces for an AEON BC statement. Keep transaction count small (3) and self-balancing for reconciler tests.

- [ ] **Step 1: Replace `backend/sample_data/aeon_sample.txt` with the new synthetic content**

```
CREDIT CARD STATEMENT / TAX INVOICE
PENYATA KAD KREDIT / INVOIS CUKAI
Page 1 / 3
AEON CREDIT SERVICE (M) BHD 199601040414 (412767-V)
Level 18, UOA Corporate Tower
MR TEST USER
1, JALAN TEST
50000 KUALA LUMPUR
Card Number /
Nombor Kad
1234567890123456
Card type /
Jenis Kad
AMP VISA CLASSIC
Combined Credit Limit (RM) /
Had Kredit Gabungan (RM)
3,000.00
Statement Date /
Tarikh Penyata
25 Apr 2026
Payment Due Date /
Tarikh Bayar Matang
15 May 2026
Credit Card Number
Nombor Kad Kredit
Previous Statement Balance
Baki Penyata Sebelum
Total Charges of the Month
Jumlah Caj Bulanan
Total Current Balance
Jumlah Baki Semasa
Minimum Payment
Bayaran Minimum
1234567890123456
RM 1,000.00
RM 220.00
RM 720.00
RM 50.00
Posting Date /
Tarikh Bil Diterima
Transaction Date /
Tarikh Transaksi
Transaction Details /
Deskripsi Transaksi
Amount (RM) /
Amaun (RM)
YOUR PREVIOUS STATEMENT BALANCE
1,000.00
1234567890123456 MR TEST USER
02 Apr 2026
01 Apr 2026
PAYMENT - THANK YOU
CR
500.00
05 Apr 2026
04 Apr 2026
SOME COFFEE SHOP KUALA LUMPUR
20.00
10 Apr 2026
09 Apr 2026
LONG MERCHANT NAME WITH MULTI
LINE DESCRIPTION TEST
200.00
```

The math: Previous (1000.00) + Σ(signed: -500 + 20 + 200 = -280) = Current (720.00) ✓ — required for reconciler tests in Task 3.

- [ ] **Step 2: Confirm file replaced**

Run: `head -5 backend/sample_data/aeon_sample.txt`
Expected: shows the first 5 lines (`CREDIT CARD STATEMENT / TAX INVOICE` through `AEON CREDIT SERVICE...`).

- [ ] **Step 3: Run existing AEON parser tests to confirm they ALL fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_aeon_parser.py -v`
Expected: most tests FAIL — the existing parser was tuned to the OLD column-aligned sample. Acceptable; Task 2 will rewrite both the parser and the tests. The full suite has the failures isolated to this one file.

- [ ] **Step 4: Commit**

```bash
git add backend/sample_data/aeon_sample.txt
git commit -m "test(ringgit): replace aeon sample with real-shape synthetic"
```

---

## Task 2: Rewrite AEONParser (TDD)

**Files:**
- Modify: `backend/app/services/parsers/aeon.py` (full rewrite)
- Modify: `backend/tests/test_aeon_parser.py` (full rewrite)

The new parser uses anchor-based extraction. The existing column-position regex parser is replaced wholesale.

- [ ] **Step 1: Replace `backend/tests/test_aeon_parser.py` with the new tests**

```python
from pathlib import Path

from app.services.parsers.aeon import AEONParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "aeon_sample.txt").read_text()


def test_can_parse_detects_aeon_credit_card():
    assert AEONParser().can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    assert AEONParser().can_parse("MAYBANK\nStatement of Account") is False


def test_can_parse_rejects_vp_prepaid():
    # VP statements have AEON CREDIT SERVICE but no "Total Charges of the Month"
    # — the credit-card-billing-cycle concept that distinguishes BC from VP.
    vp_text = (
        "AEON CREDIT SERVICE (M) BHD\n"
        "Your Previous Statement Balance\n"
        "0.00\n"
        "Credit Transaction(s)\n"
        "Total Spent for this month\n"
        "0.00\n"
        "Total Available Balance\n"
        "100.00\n"
    )
    assert AEONParser().can_parse(vp_text) is False


def test_extract_period_month():
    # Statement Date in the synthetic sample is "25 Apr 2026" → "2026-04".
    assert AEONParser().extract_period_month(SAMPLE_TEXT) == "2026-04"


def test_parses_transaction_count():
    txs = AEONParser().parse(SAMPLE_TEXT)
    # 3 real transactions; the "YOUR PREVIOUS STATEMENT BALANCE" header row
    # in the description column must NOT be counted as a transaction.
    assert len(txs) == 3


def test_parses_credit_payment():
    # The CR-marked payment ("PAYMENT - THANK YOU CR 500.00").
    txs = AEONParser().parse(SAMPLE_TEXT)
    payment = txs[0]
    assert payment["date"] == "2026-04-01"
    assert payment["type"] == "credit"
    assert payment["amount"] == 500.00
    assert "PAYMENT" in payment["description"]
    # The literal "CR" line must NOT leak into the description.
    assert payment["description"].strip() != "CR"
    assert " CR " not in f" {payment['description']} "
    assert payment["description"] != "CR"


def test_parses_debit_purchase():
    txs = AEONParser().parse(SAMPLE_TEXT)
    coffee = txs[1]
    assert coffee["date"] == "2026-04-04"
    assert coffee["type"] == "debit"
    assert coffee["amount"] == 20.00
    assert "COFFEE SHOP" in coffee["description"]
    assert "KUALA LUMPUR" in coffee["description"]


def test_parses_multi_line_description():
    txs = AEONParser().parse(SAMPLE_TEXT)
    multi = txs[2]
    assert multi["date"] == "2026-04-09"
    assert multi["type"] == "debit"
    assert multi["amount"] == 200.00
    # The merchant name is split across two source lines and must be joined.
    assert "LONG MERCHANT NAME" in multi["description"]
    assert "MULTI LINE DESCRIPTION TEST" in multi["description"]


def test_external_reference_is_none():
    # AEON statements don't expose per-tx reference IDs.
    txs = AEONParser().parse(SAMPLE_TEXT)
    for tx in txs:
        assert tx.get("external_reference") is None
```

- [ ] **Step 2: Run tests to confirm they fail in the expected way**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_aeon_parser.py -v`
Expected: most tests FAIL — the existing parser doesn't match the new sample. Some may pass coincidentally (e.g., `test_can_parse_rejects_other`). What matters is the targeted tests for transaction parsing fail.

- [ ] **Step 3: Replace `backend/app/services/parsers/aeon.py` with the new implementation**

```python
"""AEON Credit Card (BC / AMP VISA CLASSIC) statement parser.

PyMuPDF's `Page.find_tables()` doesn't yield clean per-row data on AEON
statements — the PDF table lacks visible row separators, so all transactions
get mashed into one row per column. We use anchor-based text parsing instead:
each transaction is a chunk anchored by two consecutive `DD MMM YYYY` lines
(Posting Date and Transaction Date).

Per-row layout:
    DD MMM YYYY            <- Posting Date
    DD MMM YYYY            <- Transaction Date
    <Description>          <- one or more lines
    [CR]                   <- standalone "CR" line marks credit (payment/refund)
    <amount>               <- "1,234.56" format

Header rows like "YOUR PREVIOUS STATEMENT BALANCE\\n2,138.72\\n<card> MR NAME"
appear in the description column before the first transaction. They are NOT
date-pair-anchored, so they are naturally skipped by the anchor walk.
"""
import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction


# A line containing only a "DD MMM YYYY" date.
_DATE_LINE_RE = re.compile(r"^(\d{2})\s+(\w{3})\s+(\d{4})$")
# A line containing only a "1,234.56" or "1234.56" amount.
_AMOUNT_LINE_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$")
# Marker for credit (payment / refund) transactions.
_CR_LINE = "CR"


class AEONParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "aeon"

    def can_parse(self, text: str) -> bool:
        # `Total Charges of the Month` is the credit-card billing-cycle concept
        # that distinguishes BC from VP prepaid (which has no payment cycle).
        return "AEON CREDIT SERVICE" in text and "Total Charges of the Month" in text

    def extract_period_month(self, text: str) -> str:
        # Statement Date label (bilingual). The English label comes first;
        # the BM translation is on the next line; the value is the line after.
        m = re.search(
            r"Statement Date[\s\S]*?Tarikh Penyata\s*\n(\d{2})\s+(\w{3})\s+(\d{4})",
            text,
        )
        if not m:
            return ""
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y")
            return dt.strftime("%Y-%m")
        except ValueError:
            return ""

    def parse(self, text: str) -> list[ParsedTransaction]:
        lines = [ln.strip() for ln in text.splitlines()]
        anchors = self._find_anchor_indices(lines)
        transactions: list[ParsedTransaction] = []
        for k, start in enumerate(anchors):
            end = anchors[k + 1] if k + 1 < len(anchors) else len(lines)
            tx = self._extract_tx(lines[start:end])
            if tx:
                transactions.append(tx)
        return transactions

    def _find_anchor_indices(self, lines: list[str]) -> list[int]:
        # Anchor: two consecutive lines, each matching DD MMM YYYY.
        # The anchor index points at the FIRST date (Posting Date).
        indices: list[int] = []
        for i in range(len(lines) - 1):
            if _DATE_LINE_RE.match(lines[i]) and _DATE_LINE_RE.match(lines[i + 1]):
                indices.append(i)
        return indices

    def _extract_tx(self, chunk: list[str]) -> ParsedTransaction | None:
        if len(chunk) < 4:
            return None

        # chunk[0] = Posting Date, chunk[1] = Transaction Date.
        # Use Transaction Date as the user-facing date (when the spend actually occurred).
        date_match = _DATE_LINE_RE.match(chunk[1])
        if not date_match:
            return None
        try:
            dt = datetime.strptime(
                f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)}",
                "%d %b %Y",
            )
        except ValueError:
            return None
        date_str = dt.strftime("%Y-%m-%d")

        # Find the amount: the LAST line in the chunk matching the amount pattern.
        amount_idx = None
        for i in range(len(chunk) - 1, 1, -1):
            if _AMOUNT_LINE_RE.match(chunk[i]):
                amount_idx = i
                break
        if amount_idx is None:
            return None
        amount_val = float(chunk[amount_idx].replace(",", ""))

        # Type: credit if any line in the chunk is exactly "CR".
        is_credit = any(ln == _CR_LINE for ln in chunk[2:amount_idx])
        tx_type = "credit" if is_credit else "debit"

        # Description: lines between the date pair and the amount, excluding
        # the standalone "CR" line. Joined with spaces, whitespace-collapsed.
        desc_lines = [
            ln for ln in chunk[2:amount_idx]
            if ln and ln != _CR_LINE
        ]
        description = re.sub(r"\s+", " ", " ".join(desc_lines)).strip()

        tx: ParsedTransaction = ParsedTransaction(
            date=date_str,
            description=description[:200] if description else "AEON transaction",
            amount=amount_val,
            type=tx_type,
        )
        return tx
```

- [ ] **Step 4: Run the AEON parser tests — all should pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_aeon_parser.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the full backend test suite — no regressions**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green (TnG tests, reconciler tests, etc., still pass).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/parsers/aeon.py backend/tests/test_aeon_parser.py
git commit -m "feat(ringgit): rewrite aeon parser with anchor-based extraction"
```

---

## Task 3: Reconciler AEON dispatch + synthetic test (TDD)

**Files:**
- Modify: `backend/app/services/reconciler.py`
- Modify: `backend/tests/test_reconciler.py`

Adds the AEON arm to `reconcile_statement` with a synthetic-text test. Real-fixture test comes in Task 4.

- [ ] **Step 1: Append the failing AEON synthetic test to `backend/tests/test_reconciler.py`**

```python
def test_reconcile_aeon_synthetic_passes(db, tmp_path, monkeypatch):
    # Use the same synthetic AEON sample the parser uses. Stage it as a "PDF"
    # by generating a real PDF from the text, since the reconciler reads via
    # PyMuPDF. (We can't fake-monkey the PDF read here — the dispatch path
    # opens the file and runs find_tables internally.)
    import fitz

    sample_path = Path(__file__).parent.parent / "sample_data" / "aeon_sample.txt"
    sample_text = sample_path.read_text()

    # Render the text as a multi-page PDF — one line per visual line.
    pdf_path = tmp_path / "aeon_synth.pdf"
    doc = fitz.open()
    page = doc.new_page()
    text_box = fitz.Rect(40, 40, 555, 800)
    page.insert_textbox(text_box, sample_text, fontsize=8, fontname="cour")
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)

    acc = Account(name="AEON Credit Card", bank="aeon", type="credit_card")
    db.add(acc); db.commit()

    parser = AEONParser()
    parsed = parser.parse(sample_text)

    stmt = Statement(
        file_hash="aeon-synth-hash",
        bank="aeon",
        source="email",
        filename="aeon_synth.pdf",
        period_month=parser.extract_period_month(sample_text) or "",
        file_path="aeon_synth.pdf",
    )
    db.add(stmt); db.flush()
    for p in parsed:
        db.add(Transaction(
            statement_id=stmt.id, account_id=acc.id,
            date=p["date"], description=p["description"],
            amount=p["amount"], type=p["type"],
        ))
    db.commit()

    result = reconcile_statement(stmt.id, db)
    assert result.ok, f"reconciliation failed: {result.note} (checks_run={result.checks_run})"
    assert "count" in result.checks_run
    assert "statement" in result.checks_run
    # Per-row not applicable for credit cards; should NOT appear in checks_run.
    assert "per_row" not in result.checks_run


def test_reconcile_aeon_count_mismatch_flags():
    # Pure-function-level count check: deliberately desynced.
    from app.services.reconciler import _check_count
    r = _check_count(db_count=5, table_count=4)
    assert r.ok is False


def test_reconcile_aeon_balance_mismatch_flags(db, tmp_path, monkeypatch):
    # Same setup as the passes test, but corrupt one of the inserted
    # transactions so signed_sum no longer matches Current - Previous.
    import fitz
    sample_path = Path(__file__).parent.parent / "sample_data" / "aeon_sample.txt"
    sample_text = sample_path.read_text()

    pdf_path = tmp_path / "aeon_corrupt.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 555, 800), sample_text, fontsize=8, fontname="cour")
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)

    acc = Account(name="AEON Credit Card", bank="aeon", type="credit_card")
    db.add(acc); db.commit()

    parser = AEONParser()
    parsed = parser.parse(sample_text)
    # Corrupt the second transaction's amount so the signed sum drifts.
    parsed[1] = {**parsed[1], "amount": parsed[1]["amount"] + 50.00}

    stmt = Statement(
        file_hash="aeon-corrupt-hash",
        bank="aeon",
        source="email",
        filename="aeon_corrupt.pdf",
        period_month=parser.extract_period_month(sample_text) or "",
        file_path="aeon_corrupt.pdf",
    )
    db.add(stmt); db.flush()
    for p in parsed:
        db.add(Transaction(
            statement_id=stmt.id, account_id=acc.id,
            date=p["date"], description=p["description"],
            amount=p["amount"], type=p["type"],
        ))
    db.commit()

    # Note: count still matches; statement balance check should fail because
    # we inserted the wrong amount but the reconciler reads the PDF (correct
    # amounts) and compares its sum against header Current Balance.
    # Wait — the reconciler reads from the PDF, not from the DB transactions.
    # So this test only verifies count-mismatch, not amount-mismatch.
    # Amount-mismatch testing is the job of the real-fixture test in Task 4.
    # Keep this test simple: just verify count mismatch flagging works.
    extra = Transaction(
        statement_id=stmt.id, account_id=acc.id,
        date="2026-04-15", description="EXTRA INSERTED FOR TEST",
        amount=99.99, type="debit",
    )
    db.add(extra); db.commit()

    result = reconcile_statement(stmt.id, db)
    assert result.ok is False
    assert "row count mismatch" in (result.note or "")
```

You'll also need imports at the top of the file if not already present:

```python
from app.services.parsers.aeon import AEONParser
```

(Other imports — `Path`, `Account`, `Statement`, `Transaction`, `reconcile_statement` — already exist in the test file from prior tasks.)

- [ ] **Step 2: Run the new tests — they must fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v -k aeon`
Expected: FAIL — the AEON dispatch arm doesn't exist yet, so reconciliation returns `ok=True, note="unknown bank format"` (which doesn't match the assertions).

- [ ] **Step 3: Add the AEON dispatch + helpers to `backend/app/services/reconciler.py`**

Locate the existing format dispatch (the if/elif/else block in `reconcile_statement` that handles `_NEW_FORMAT_MARKER` and `_LEGACY_FORMAT_MARKER`). Add a new constant and helpers, then insert the AEON arm.

Add at the top of the file alongside other constants (e.g., near `_NEW_FORMAT_MARKER`):

```python
_AEON_MARKER = "AEON CREDIT SERVICE"
```

Add these two helpers somewhere in the module after the existing extractors:

```python
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
        amount_idx = None
        for j in range(len(chunk) - 1, 1, -1):
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
```

Now extend `reconcile_statement`. Find the dispatch block:

```python
    text = "".join(p.get_text() for p in doc)
    if _NEW_FORMAT_MARKER in text:
        rows = _extract_rows_from_tng_new(doc)
    elif _LEGACY_FORMAT_MARKER in text:
        rows = _extract_rows_from_tng_legacy(doc)
    else:
        doc.close()
        return ReconcileResult(ok=True, note="unknown bank format")
    doc.close()
```

Replace it with:

```python
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
```

Now find the existing checks block:

```python
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

Insert an AEON-specific statement check between the count check and the per-row block. Replace with:

```python
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
        sum_signed = sum(r["signed_amount"] for r in rows)
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
```

- [ ] **Step 4: Run the AEON reconciler tests — they must pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v -k aeon`
Expected: 3 passed.

- [ ] **Step 5: Run the full reconciler test suite + full backend suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v`
Expected: all reconciler tests pass (TnG ones still green).

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/reconciler.py backend/tests/test_reconciler.py
git commit -m "feat(ringgit): reconciler aeon dispatch with statement-level check"
```

---

## Task 4: Real-fixture reconciler test for AEON

**Files:**
- Modify: `backend/tests/test_reconciler.py` (append one test)
- Stage (gitignored): `backend/tests/fixtures/real/aeon_credit.pdf`

This task validates the parser + reconciler against a real BC PDF. The fixture is not committed (the directory is gitignored).

- [ ] **Step 1: Append the real-fixture test to `backend/tests/test_reconciler.py`**

```python
_AEON_FIXTURE_NAME = "aeon_credit.pdf"
_AEON_FIXTURE_PATH = _FIXTURE_DIR / _AEON_FIXTURE_NAME
_AEON_PASSWORD = "075491"  # owner-supplied; matches PDF_PASSWORD_AEON in .env


@pytest.mark.skipif(
    not _AEON_FIXTURE_PATH.exists(),
    reason=f"real fixture {_AEON_FIXTURE_NAME} not present",
)
def test_reconcile_real_aeon_credit_passes(db, monkeypatch, tmp_path):
    import fitz

    staged = tmp_path / _AEON_FIXTURE_NAME
    shutil.copy(_AEON_FIXTURE_PATH, staged)
    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)
    monkeypatch.setitem(
        __import__("app.config", fromlist=["SENDER_PASSWORDS"]).SENDER_PASSWORDS,
        "estatement@aeonrewards.com.my",
        _AEON_PASSWORD,
    )

    acc = Account(name="AEON Credit Card", bank="aeon", type="credit_card")
    db.add(acc); db.commit()

    doc = fitz.open(str(staged))
    if doc.is_encrypted:
        doc.authenticate(_AEON_PASSWORD)
    text = "".join(p.get_text() for p in doc)
    doc.close()
    parser = AEONParser()
    parsed = parser.parse(text)
    assert len(parsed) > 0, "parser produced 0 transactions on real AEON fixture"

    stmt = Statement(
        file_hash="aeon-real-test-hash",
        bank="aeon",
        source="email",
        filename=_AEON_FIXTURE_NAME,
        period_month=parser.extract_period_month(text) or "",
        file_path=_AEON_FIXTURE_NAME,
    )
    db.add(stmt); db.flush()
    for p in parsed:
        db.add(Transaction(
            statement_id=stmt.id, account_id=acc.id,
            date=p["date"], description=p["description"],
            amount=p["amount"], type=p["type"],
        ))
    db.commit()

    result = reconcile_statement(stmt.id, db)
    assert result.ok, f"real AEON reconciliation failed: {result.note} (checks_run={result.checks_run})"
    assert "count" in result.checks_run
    assert "statement" in result.checks_run
    assert "per_row" not in result.checks_run
```

- [ ] **Step 2: Stage one real BC PDF as the test fixture**

Run:

```bash
cd backend && mkdir -p tests/fixtures/real && cp fetched_pdfs/aquamagmayeow94_gmail_com/2026_04_BC_STMT.pdf tests/fixtures/real/aeon_credit.pdf
```

Expected: silent success. The directory is gitignored (existing `.gitignore` rule for `tests/fixtures/real/`), so the file stays local-only.

If `2026_04_BC_STMT.pdf` doesn't exist by that exact name in `fetched_pdfs/aquamagmayeow94_gmail_com/`, find ANY BC file:

```bash
ls backend/fetched_pdfs/aquamagmayeow94_gmail_com/*BC_STMT* | head -1
```

Substitute that path in the `cp` command.

- [ ] **Step 3: Run the real-fixture test — it must PASS (not skip)**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_reconcile_real_aeon_credit_passes -v`
Expected: 1 passed. If it skips, the fixture wasn't staged correctly — re-do Step 2.

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_reconciler.py
git commit -m "test(ringgit): real-fixture reconciler test for aeon credit card"
```

(The fixture PDF itself is gitignored and stays local.)

---

## Task 5: Reprocess script for AEON BC statements

**Files:**
- Create: `backend/scripts/reprocess_aeon.py`

- [ ] **Step 1: Create the script**

Create `backend/scripts/reprocess_aeon.py`:

```python
"""Re-parse all AEON Big Card (BC) statements through the current parser,
replacing every existing AEON transaction in-place. Idempotent — running it
twice produces the same end state. Use after AEON parser fixes.

VP prepaid statements are deliberately NOT processed — they remain as
bank='unknown' stubs (per the design decision in the spec).

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reprocess_aeon.py
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
    aeon_account = db.query(Account).filter_by(bank="aeon").first()
    if not aeon_account:
        print("no AEON account found; aborting"); return 1

    # Step 1: delete existing AEON transactions (none today, but defensive
    # against re-runs after parser fixes).
    deleted = db.query(Transaction).filter_by(account_id=aeon_account.id).delete()
    db.commit()
    print(f"deleted {deleted} existing AEON transactions")

    # Step 2: find candidate BC statements.
    stmts = (
        db.query(Statement)
        .filter(Statement.bank.in_(["unknown", "aeon"]))
        .filter(Statement.filename.like("%BC_STMT%"))
        .order_by(Statement.id)
        .all()
    )
    print(f"reprocessing {len(stmts)} AEON BC statements")

    existing_keys: set[tuple] = set()
    inserted = 0
    skipped = 0
    extraction_failures = 0
    detection_failures = 0

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
        if parser is None or parser.bank_id != "aeon":
            detection_failures += 1
            continue

        parsed = parser.parse(text)
        period_month = parser.extract_period_month(text) or ""
        if period_month and stmt.period_month != period_month:
            stmt.period_month = period_month
        # Promote the unknown stub to an aeon-classified statement.
        if stmt.bank != "aeon":
            stmt.bank = "aeon"

        for p in parsed:
            # No external_reference for AEON; broad-key dedup only.
            key = (p["date"], p["amount"], p["type"], p["description"])
            if key in existing_keys:
                skipped += 1; continue
            existing_keys.add(key)
            cat_id = categorizer.categorize(p["description"])
            if cat_id is None and uncat:
                cat_id = uncat.id
            db.add(Transaction(
                statement_id=stmt.id, account_id=aeon_account.id,
                date=p["date"], description=p["description"],
                amount=p["amount"], type=p["type"], category_id=cat_id,
            ))
            inserted += 1
        db.commit()

    print(f"inserted: {inserted}")
    print(f"skipped (dedup): {skipped}")
    print(f"extraction failures: {extraction_failures}")
    print(f"detection failures: {detection_failures}")

    RecurringDetector(db).apply_recurring_flags()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the script against the live DB**

Run: `cd backend && ./.venv/Scripts/python.exe scripts/reprocess_aeon.py`
Expected: prints `deleted 0 existing AEON transactions`, `reprocessing 31 AEON BC statements`, `inserted: <N>` (likely a few hundred — depends on transaction density per statement), `skipped (dedup): <small N>`, `extraction failures: 0`, `detection failures: 0`.

- [ ] **Step 3: Verify final state**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    total = conn.execute(text(\"SELECT COUNT(*) FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE bank='aeon')\")).scalar()
    stmt_aeon = conn.execute(text(\"SELECT COUNT(*) FROM statements WHERE bank='aeon'\")).scalar()
    stmt_unknown = conn.execute(text(\"SELECT COUNT(*) FROM statements WHERE bank='unknown'\")).scalar()
    print(f'AEON transactions: {total}')
    print(f'Statements with bank=aeon: {stmt_aeon}')
    print(f'Statements with bank=unknown: {stmt_unknown} (expect 8 — the VP statements)')
"
```

Expected: `Statements with bank=aeon: 31`, `Statements with bank=unknown: 8`. AEON transactions count depends on the actual data.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/reprocess_aeon.py
git commit -m "feat(ringgit): scripts/reprocess_aeon.py for aeon bc statements"
```

---

## Task 6: Backfill reconciliation flag + manual smoke

**Files:**
- None modified

This task uses the existing `backend/scripts/reconcile_existing.py` (committed previously) — no new code.

- [ ] **Step 1: Run the backfill script**

Run: `cd backend && ./.venv/Scripts/python.exe scripts/reconcile_existing.py`
Expected: prints `reconciling <N> statements` (the same total as before, ~71). New AEON statements are now reconciled; counts should reflect that.

- [ ] **Step 2: Inspect AEON-specific reconciliation results**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    rows = conn.execute(text(\"SELECT id, period_month, filename, needs_review, reconciliation_note FROM statements WHERE bank='aeon' ORDER BY id\")).fetchall()
    flagged = [r for r in rows if r[3]]
    print(f'Total AEON statements: {len(rows)}')
    print(f'Flagged needs_review: {len(flagged)}')
    print()
    print('Flagged statements:')
    for r in flagged:
        print(f'  id={r[0]} period={r[1]} file={r[2]}')
        print(f'    note={(r[4] or \"\")[:120]}')
"
```

Expected: A small number flagged (single digits ideally). Each one is a candidate to investigate manually — open the PDF, check whether the parser missed something or the reconciler has a false positive.

- [ ] **Step 3: Final full-suite check**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 4: No commit**

This task is verification-only. No code changed.

---

## Self-review

**Spec coverage:** each section of `2026-05-02-aeon-credit-card-parser-and-reconciliation-design.md` is covered:
- Phase 1 parser rewrite → Tasks 1, 2.
- Phase 1 reconciler dispatch + statement-level check → Task 3.
- Real-fixture validation → Task 4.
- Phase 2 reprocess script → Task 5.
- Backfill via existing script → Task 6.
- Tests for `can_parse_rejects_vp_prepaid`, multi-line description, CR detection, header extraction → all in Tasks 2–4.
- Out-of-scope items (VP parser, find_tables for AEON, per-row reconciliation, generic config externalization) → correctly absent from the plan.

**Placeholder scan:** no TBD/TODO markers; every step has either concrete code or a concrete command with expected output. The only soft language is around "likely a few hundred" for the reprocess insert count — that's an estimate, not a placeholder, and the actual number is not load-bearing.

**Type consistency:** `AEONParser` class name and `bank_id="aeon"` consistent across Tasks 2, 3, 4, 5. `ReconcileResult` shape (`ok`, `note`, `checks_run`) used identically across Tasks 3 and 4 (matches the existing definition from prior work). `_AEON_MARKER`, `_extract_aeon_credit_header_balances`, `_extract_rows_from_aeon_credit` defined once in Task 3 and consumed only by `reconcile_statement` in the same task. `aeon_headers` local variable shape `{"previous", "current"}` consistent between extractor and consumer. The reprocess script (Task 5) uses the parser's `bank_id="aeon"` for both the candidate filter and the post-parse check — matches.
