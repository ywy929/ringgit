# Maybank Savings Parser + Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a working Maybank savings account parser (sender `m2u@stmts.maybank2u.com.my`) that handles both the 2018 GST-era format and the post-GST 2026 format, extend the reconciler with per-row + statement-level checks, and reprocess the 61 existing encrypted-stub statements through the new parser.

**Architecture:** The current `MaybankParser` is column-position regex tuned to a fictional sample. Full rewrite uses anchor-based extraction (each `^DD/MM/YY$` line is a transaction anchor) — same approach as TnG and AEON. A single parser handles both eras by walking forward through each chunk to find the sign-suffixed amount line (`442.00-` or `500.00+`), naturally skipping the optional GST column line in old-format statements. Reconciler gets a fourth dispatch arm with both per-row check (running balance available on every row) and statement-level check (BEGINNING BALANCE always present; ENDING BALANCE present only in 2018-era statements).

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, PyMuPDF (`fitz`), pytest. No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-05-02-maybank-savings-parser-design.md`

---

## File Map

### Modified files
- `backend/sample_data/maybank_sample.txt` — replaced with real-shape 2026-format synthetic
- `backend/app/services/parsers/maybank.py` — full rewrite, anchor-based parser
- `backend/tests/test_maybank_parser.py` — full rewrite to match new parser
- `backend/app/services/reconciler.py` — add `_MAYBANK_MARKER`, `_MAYBANK_MARKER_2`, `_extract_maybank_balances`, `_extract_rows_from_maybank`, fourth dispatch arm in `reconcile_statement` with inline beginning/ending balance cross-checks
- `backend/tests/test_reconciler.py` — append synthetic Maybank tests + real-fixture test

### New files
- `backend/sample_data/maybank_2018_sample.txt` — synthetic 2018-format text including the GST column
- `backend/scripts/reprocess_maybank.py` — one-shot script to convert the 61 encrypted-stub Maybank statements into parsed Maybank transactions
- `backend/tests/fixtures/real/maybank_savings.pdf` — staged real PDF for reconciler integration test (gitignored)

### Untouched
- `backend/app/services/parser_registry.py` — `MaybankParser` is already registered; no change needed
- `backend/app/models.py` — no schema change
- `backend/scripts/reconcile_existing.py` — exists from previous work; just re-run after reprocess
- `backend/app/config.py` — `PDF_PASSWORD_MAYBANK` is already wired into `SENDER_PASSWORDS`

---

## Task 1: Replace Maybank sample text with real-shape synthetics

**Files:**
- Modify: `backend/sample_data/maybank_sample.txt`
- Create: `backend/sample_data/maybank_2018_sample.txt`

The current `maybank_sample.txt` is column-aligned fictional text that won't match real PyMuPDF output. Replace with a line-by-line dump matching the actual extracted-text shape of a Maybank savings statement (post-GST 2026 format). Add a second sample for the GST-era 2018 format.

The samples are designed to be reconciliation-self-balancing so they work for both parser unit tests and reconciler tests:
- **2026 sample:** beginning 1,000.00, then `+500.00` (credit deposit), `-200.00` (debit transfer with multi-line detail), `+50.00` (credit refund). Final balance: 1,350.00. No ENDING BALANCE marker (2026 dropped it).
- **2018 sample:** beginning 0.00, then `+250.00` (CASH DEPOSIT, no GST), `-8.48` (DEBIT ADVICE with `SR` GST line + indented gst-detail), `+100.00` (CRDESC with multi-line detail). Final balance: 341.52. ENDING BALANCE: 341.52, TOTAL CREDIT: 350.00, TOTAL DEBIT: 8.48.

- [ ] **Step 1: Replace `backend/sample_data/maybank_sample.txt` with the new 2026-format synthetic content**

```
URUSNIAGA AKAUN/ 戶口進支項/ACCOUNT TRANSACTIONS
TARIKH MASUK
BUTIR URUSNIAGA
JUMLAH URUSNIAGA
BAKI PENYATA
進支日期
進支項說明
银碼
結單存餘
ENTRY DATE
TRANSACTION DESCRIPTION
TRANSACTION AMOUNT
STATEMENT BALANCE
BEGINNING BALANCE
1,000.00
02/03/26
TRANSFER FROM A/C
500.00+
1,500.00
06/03/26
TRANSFER TO A/C
200.00-
1,300.00
   SITTAL CARPARK SDN.*
   SITTAL CARPARK
10/03/26
REFUND
50.00+
1,350.00
TARIKH PENYATA
結單日期
STATEMENT DATE
:
31/03/26
NOMBOR AKAUN
戶號
ACCOUNT
NUMBER
:
XXXXXX-XXXXXX
SAVINGS ACCOUNT
TERMS AND CONDITION APPLY.
Malayan Banking Berhad (3813-K)
```

The math: 1000.00 + (+500 - 200 + 50) = 1350.00 ✓. This is required by reconciler tests in Task 3.

- [ ] **Step 2: Create `backend/sample_data/maybank_2018_sample.txt` with the new 2018-format synthetic content**

```
URUSNIAGA AKAUN/ 戶口進支項/ACCOUNT TRANSACTIONS
TARIKH MASUK
BUTIR URUSNIAGA
JENIS GST
JUMLAH URUSNIAGA
BAKI PENYATA
進支日期
進支項說明
種類
银碼
結單存餘
ENTRY DATE
TRANSACTION DESCRIPTION
GST TYPE
TRANSACTION AMOUNT
STATEMENT BALANCE
BEGINNING BALANCE
0.00
05/03/18
CASH DEPOSIT
250.00+
250.00
06/03/18
DEBIT ADVICE     SR
SR
8.48-
241.52
   (INCLUSIVE OF GST RM     0.48)
25/03/18
CRDESC
100.00+
341.52
   FROM ACME PAYROLL
   PAYREF
ENDING BALANCE :
341.52
TOTAL CREDIT :
350.00
TOTAL DEBIT :
8.48
TARIKH PENYATA
結單日期
STATEMENT DATE
:
31/03/18
SAVINGS ACCOUNT
TERMS AND CONDITION APPLY.
Malayan Banking Berhad (3813-K)
```

The math: 0.00 + (+250 - 8.48 + 100) = 341.52 ✓. Matches the ENDING BALANCE line.

- [ ] **Step 3: Confirm both files exist**

Run: `ls backend/sample_data/maybank*.txt`
Expected: lists `maybank_sample.txt` and `maybank_2018_sample.txt`.

- [ ] **Step 4: Run existing Maybank parser tests to confirm they ALL fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_maybank_parser.py -v`
Expected: most/all tests FAIL — the existing parser was tuned to the OLD column-aligned sample. Acceptable; Task 2 will rewrite both the parser and the tests.

- [ ] **Step 5: Commit**

```bash
git add backend/sample_data/maybank_sample.txt backend/sample_data/maybank_2018_sample.txt
git commit -m "test(ringgit): replace maybank sample with real-shape synthetics for both eras"
```

---

## Task 2: Rewrite MaybankParser (TDD)

**Files:**
- Modify: `backend/app/services/parsers/maybank.py` (full rewrite)
- Modify: `backend/tests/test_maybank_parser.py` (full rewrite)

The new parser uses anchor-based extraction. Each `^DD/MM/YY$` line marks a transaction; within the chunk we walk forward to find a sign-suffixed amount. The single parser handles both 2018 (GST column present) and 2026 (no GST column) formats by virtue of walking forward — the GST line (`SR`) doesn't match the signed-amount regex and is naturally skipped.

- [ ] **Step 1: Replace `backend/tests/test_maybank_parser.py` with the new tests**

```python
from pathlib import Path

from app.services.parsers.maybank import MaybankParser

SAMPLE_2026 = (Path(__file__).parent.parent / "sample_data" / "maybank_sample.txt").read_text()
SAMPLE_2018 = (Path(__file__).parent.parent / "sample_data" / "maybank_2018_sample.txt").read_text()


def test_can_parse_detects_maybank_2026():
    assert MaybankParser().can_parse(SAMPLE_2026) is True


def test_can_parse_detects_maybank_2018():
    assert MaybankParser().can_parse(SAMPLE_2018) is True


def test_can_parse_rejects_just_maybank_word():
    # The word MAYBANK alone is not enough — we need both definitive markers.
    text = "MAYBANK\nSomething Statement of Account\n"
    assert MaybankParser().can_parse(text) is False


def test_can_parse_rejects_aeon():
    text = (
        "AEON CREDIT SERVICE (M) BHD\n"
        "Total Charges of the Month\n"
        "Statement Date / Tarikh Penyata\n"
        "25 Apr 2026\n"
    )
    assert MaybankParser().can_parse(text) is False


def test_can_parse_rejects_tng():
    text = "TNG WALLET TRANSACTION HISTORY\nDate Status Type\n"
    assert MaybankParser().can_parse(text) is False


def test_extract_period_month_2026():
    assert MaybankParser().extract_period_month(SAMPLE_2026) == "2026-03"


def test_extract_period_month_2018():
    assert MaybankParser().extract_period_month(SAMPLE_2018) == "2018-03"


def test_century_inference_via_strptime():
    # Python's %y treats 00-68 as 20XX and 69-99 as 19XX. Maybank data falls
    # in 18-26, well inside 20XX. Confirm via the parser's date-anchor handling.
    parser = MaybankParser()
    txs_2026 = parser.parse(SAMPLE_2026)
    assert txs_2026[0]["date"].startswith("2026-")
    txs_2018 = parser.parse(SAMPLE_2018)
    assert txs_2018[0]["date"].startswith("2018-")


def test_parses_2026_format_count():
    txs = MaybankParser().parse(SAMPLE_2026)
    assert len(txs) == 3, f"expected 3 transactions, got {len(txs)}: {txs}"


def test_parses_2026_credit_first_transaction():
    txs = MaybankParser().parse(SAMPLE_2026)
    first = txs[0]
    assert first["date"] == "2026-03-02"
    assert first["type"] == "credit"
    assert first["amount"] == 500.00
    assert first["description"] == "TRANSFER FROM A/C"


def test_parses_2026_debit_with_multi_line_description():
    txs = MaybankParser().parse(SAMPLE_2026)
    second = txs[1]
    assert second["date"] == "2026-03-06"
    assert second["type"] == "debit"
    assert second["amount"] == 200.00
    # Description joins type label + indented detail lines.
    assert "TRANSFER TO A/C" in second["description"]
    assert "SITTAL CARPARK SDN" in second["description"]
    assert "SITTAL CARPARK" in second["description"]


def test_parses_2026_credit_third_transaction_no_details():
    txs = MaybankParser().parse(SAMPLE_2026)
    third = txs[2]
    assert third["date"] == "2026-03-10"
    assert third["type"] == "credit"
    assert third["amount"] == 50.00
    # No detail lines, so description == type label only (no trailing " - ").
    assert third["description"] == "REFUND"


def test_parses_2018_format_count():
    txs = MaybankParser().parse(SAMPLE_2018)
    assert len(txs) == 3, f"expected 3 transactions, got {len(txs)}: {txs}"


def test_parses_2018_skips_gst_line():
    # The DEBIT ADVICE transaction in the 2018 sample has a standalone "SR"
    # line between the type label and the amount. The parser must not treat
    # SR as an amount or as the type label of a separate transaction.
    txs = MaybankParser().parse(SAMPLE_2018)
    debit = txs[1]
    assert debit["date"] == "2018-03-06"
    assert debit["type"] == "debit"
    assert debit["amount"] == 8.48
    assert "DEBIT ADVICE" in debit["description"]
    # The GST detail line gets joined into the description (acceptable).
    assert "INCLUSIVE OF GST" in debit["description"]


def test_parses_2018_cash_deposit_no_gst_line():
    # CASH DEPOSIT in old format has no GST line (transaction is GST-exempt).
    txs = MaybankParser().parse(SAMPLE_2018)
    deposit = txs[0]
    assert deposit["date"] == "2018-03-05"
    assert deposit["type"] == "credit"
    assert deposit["amount"] == 250.00
    assert deposit["description"] == "CASH DEPOSIT"


def test_skips_beginning_balance_as_transaction():
    # BEGINNING BALANCE is an anchor for the reconciler, not a transaction.
    # The parser must not emit a phantom row for it.
    txs = MaybankParser().parse(SAMPLE_2026)
    descriptions = [t["description"] for t in txs]
    assert not any("BEGINNING BALANCE" in d for d in descriptions)


def test_skips_ending_balance_as_transaction():
    # ENDING BALANCE is the 2018-format footer marker, not a transaction.
    txs = MaybankParser().parse(SAMPLE_2018)
    descriptions = [t["description"] for t in txs]
    assert not any("ENDING BALANCE" in d for d in descriptions)
    assert not any("TOTAL CREDIT" in d for d in descriptions)
    assert not any("TOTAL DEBIT" in d for d in descriptions)
```

- [ ] **Step 2: Run tests to confirm they fail in the expected way**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_maybank_parser.py -v`
Expected: most tests FAIL (assertion errors or missing transactions). The existing parser doesn't match the new samples.

- [ ] **Step 3: Replace `backend/app/services/parsers/maybank.py` with the new implementation**

```python
"""Maybank savings account statement parser.

Maybank statements have evolved across two eras:

  - **Pre-September 2018 (GST era):** includes a `JENIS GST / GST TYPE`
    column with codes like `SR` (standard rated), `ES` (exempt supply), `ZR`
    (zero rated). Footer has explicit `ENDING BALANCE :` / `TOTAL CREDIT :` /
    `TOTAL DEBIT :` summary.
  - **Post-September 2018 (post-GST):** GST column dropped after Malaysia
    abolished GST and replaced it with SST. Footer no longer has the
    explicit ending-balance trio.

Both eras share the same per-transaction structure:

    DD/MM/YY            <- date anchor (line by itself, 2-digit year)
    <TYPE LABEL>        <- e.g., "TRANSFER FROM A/C", "DEBIT ADVICE     SR"
    [SR]                <- GST column line (old format only, optional)
    <amount><sign>      <- e.g., "442.00-" (debit), "500.00+" (credit)
    <balance>           <- running statement balance (no sign suffix)
    [   <detail 1>]     <- 0..N indented detail lines (merchant, references)
    [   <detail 2>]
    ...

The parser anchors on date lines and walks forward within each chunk to
find the first signed-amount line. The optional GST line in old-format
statements falls between the type label and the amount, and is naturally
skipped because it doesn't match the signed-amount regex.
"""
import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction


# A line containing only `DD/MM/YY`.
_DATE_LINE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
# A line containing only an amount with sign suffix: `442.00-` or `500.00+`.
_SIGNED_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}[+-]$")
# A line containing only a balance (no sign suffix).
_BALANCE_RE = re.compile(r"^[\d,]+\.\d{2}$")
# Statement Date label (trilingual block); we match the English label and walk
# forward to the next DD/MM/YY-only line.
_STATEMENT_DATE_RE = re.compile(
    r"STATEMENT DATE\s*\n\s*:\s*\n(\d{2}/\d{2}/\d{2})"
)

# Transaction-section terminators (any of these ends the transaction stream).
_END_MARKERS = (
    "ENDING BALANCE :",
    "TARIKH PENYATA",          # statement-date block (appears after txs in the layout)
    "TERMS AND CONDITION",
    "Malayan Banking Berhad",
)


class MaybankParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "maybank"

    def can_parse(self, text: str) -> bool:
        # Two-marker strict check: the bank name AND the BM transaction-section
        # header. Just the word "MAYBANK" is too weak (it may appear in
        # unrelated banks' marketing or in cross-bank reference data).
        return "Malayan Banking Berhad" in text and "URUSNIAGA AKAUN" in text

    def extract_period_month(self, text: str) -> str:
        m = _STATEMENT_DATE_RE.search(text)
        if not m:
            return ""
        try:
            dt = datetime.strptime(m.group(1), "%d/%m/%y")
            return dt.strftime("%Y-%m")
        except ValueError:
            return ""

    def parse(self, text: str) -> list[ParsedTransaction]:
        lines = text.splitlines()

        # Find the start of the transactions section: the line right after
        # `BEGINNING BALANCE` (which is followed by an amount line we skip).
        start_idx = None
        for i, ln in enumerate(lines):
            if ln.strip() == "BEGINNING BALANCE":
                start_idx = i + 2  # skip the BEGINNING BALANCE line and its amount
                break
        if start_idx is None:
            return []

        # Find the end: first occurrence of any END_MARKER after start_idx.
        end_idx = len(lines)
        for i in range(start_idx, len(lines)):
            stripped = lines[i].strip()
            if any(stripped.startswith(m) for m in _END_MARKERS):
                end_idx = i
                break

        section = lines[start_idx:end_idx]

        # Find anchor indices (date-only lines) within the section.
        anchors: list[int] = []
        for i, ln in enumerate(section):
            if _DATE_LINE_RE.match(ln.strip()):
                anchors.append(i)

        transactions: list[ParsedTransaction] = []
        for k, start in enumerate(anchors):
            end = anchors[k + 1] if k + 1 < len(anchors) else len(section)
            tx = self._extract_tx(section[start:end])
            if tx:
                transactions.append(tx)
        return transactions

    def _extract_tx(self, chunk: list[str]) -> ParsedTransaction | None:
        if len(chunk) < 4:
            return None

        # chunk[0] = date line.
        date_str = chunk[0].strip()
        try:
            dt = datetime.strptime(date_str, "%d/%m/%y")
        except ValueError:
            return None
        iso_date = dt.strftime("%Y-%m-%d")

        # chunk[1] = type label (first non-empty line after the date).
        # In old-format statements the type label may include an inline GST tag
        # (e.g., "DEBIT ADVICE     SR"). We preserve it as-is.
        type_label = chunk[1].strip()
        if not type_label:
            return None

        # Walk forward from chunk[2] to find the first signed-amount line.
        # In old-format statements, a standalone "SR" GST line may appear
        # between the type label and the amount; it doesn't match the
        # signed-amount regex, so we skip past it.
        signed_idx = None
        for i in range(2, len(chunk)):
            if _SIGNED_AMOUNT_RE.match(chunk[i].strip()):
                signed_idx = i
                break
        if signed_idx is None:
            return None

        signed_line = chunk[signed_idx].strip()
        sign = signed_line[-1]  # '+' or '-'
        amount = float(signed_line[:-1].replace(",", ""))
        tx_type = "credit" if sign == "+" else "debit"

        # Balance line: must immediately follow the signed amount.
        if signed_idx + 1 >= len(chunk):
            return None
        balance_line = chunk[signed_idx + 1].strip()
        if not _BALANCE_RE.match(balance_line):
            return None

        # Detail lines: everything after the balance line, leading whitespace
        # stripped, empty lines dropped.
        detail_lines = [ln.strip() for ln in chunk[signed_idx + 2:] if ln.strip()]

        if detail_lines:
            description = f"{type_label} - {' '.join(detail_lines)}"
        else:
            description = type_label
        # Collapse internal whitespace runs (the "DEBIT ADVICE     SR" type
        # label has multiple spaces inside it).
        description = re.sub(r"\s+", " ", description).strip()

        return ParsedTransaction(
            date=iso_date,
            description=description[:200] if description else "Maybank transaction",
            amount=amount,
            type=tx_type,
        )
```

- [ ] **Step 4: Run the Maybank parser tests — all should pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_maybank_parser.py -v`
Expected: 17 passed.

- [ ] **Step 5: Run the full backend test suite — no regressions**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green (TnG, AEON, reconciler, etc., still pass).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/parsers/maybank.py backend/tests/test_maybank_parser.py
git commit -m "feat(ringgit): rewrite maybank parser with anchor-based extraction"
```

---

## Task 3: Reconciler Maybank dispatch + synthetic tests (TDD)

**Files:**
- Modify: `backend/app/services/reconciler.py`
- Modify: `backend/tests/test_reconciler.py`

Adds the Maybank arm to `reconcile_statement`. The dispatch arm uses both per-row check (Maybank always has running balance) and an inline statement-level check that cross-validates against the explicit `BEGINNING BALANCE` (always present) and `ENDING BALANCE :` (2018-era only).

- [ ] **Step 1: Append failing Maybank synthetic tests to `backend/tests/test_reconciler.py`**

Add this near the bottom of the file, after the existing AEON tests:

```python
_MAYBANK_FIXTURE_NAME = "maybank_savings.pdf"
_MAYBANK_FIXTURE_PATH = _FIXTURE_DIR / _MAYBANK_FIXTURE_NAME


def test_reconcile_maybank_2026_synthetic_passes(db, tmp_path, monkeypatch):
    # Render the 2026 sample as a real PDF and run the full reconciler path
    # against it (the reconciler reads via PyMuPDF, so we need actual PDF input).
    import fitz
    from app.services.parsers.maybank import MaybankParser

    sample_path = Path(__file__).parent.parent / "sample_data" / "maybank_sample.txt"
    sample_text = sample_path.read_text()

    pdf_path = tmp_path / "maybank_2026_synth.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 555, 800), sample_text, fontsize=8, fontname="cour")
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)

    acc = Account(name="Maybank Savings", bank="maybank", type="bank")
    db.add(acc); db.commit()

    parser = MaybankParser()
    parsed = parser.parse(sample_text)

    stmt = Statement(
        file_hash="maybank-2026-synth-hash",
        bank="maybank",
        source="email",
        filename="maybank_2026_synth.pdf",
        period_month=parser.extract_period_month(sample_text) or "",
        file_path="maybank_2026_synth.pdf",
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
    assert "per_row" in result.checks_run


def test_reconcile_maybank_2018_synthetic_passes(db, tmp_path, monkeypatch):
    # Same shape as the 2026 test, but uses the GST-era sample which has
    # the optional ENDING BALANCE :, TOTAL CREDIT :, TOTAL DEBIT : footer.
    import fitz
    from app.services.parsers.maybank import MaybankParser

    sample_path = Path(__file__).parent.parent / "sample_data" / "maybank_2018_sample.txt"
    sample_text = sample_path.read_text()

    pdf_path = tmp_path / "maybank_2018_synth.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 555, 800), sample_text, fontsize=8, fontname="cour")
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)

    acc = Account(name="Maybank Savings", bank="maybank", type="bank")
    db.add(acc); db.commit()

    parser = MaybankParser()
    parsed = parser.parse(sample_text)

    stmt = Statement(
        file_hash="maybank-2018-synth-hash",
        bank="maybank",
        source="email",
        filename="maybank_2018_synth.pdf",
        period_month=parser.extract_period_month(sample_text) or "",
        file_path="maybank_2018_synth.pdf",
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
    assert "per_row" in result.checks_run


def test_reconcile_maybank_count_mismatch_flags(db, tmp_path, monkeypatch):
    # Insert one extra transaction in the DB beyond what the PDF contains.
    import fitz
    from app.services.parsers.maybank import MaybankParser

    sample_path = Path(__file__).parent.parent / "sample_data" / "maybank_sample.txt"
    sample_text = sample_path.read_text()

    pdf_path = tmp_path / "maybank_count_mismatch.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 555, 800), sample_text, fontsize=8, fontname="cour")
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)

    acc = Account(name="Maybank Savings", bank="maybank", type="bank")
    db.add(acc); db.commit()

    parser = MaybankParser()
    parsed = parser.parse(sample_text)

    stmt = Statement(
        file_hash="maybank-count-mismatch-hash",
        bank="maybank",
        source="email",
        filename="maybank_count_mismatch.pdf",
        period_month=parser.extract_period_month(sample_text) or "",
        file_path="maybank_count_mismatch.pdf",
    )
    db.add(stmt); db.flush()
    for p in parsed:
        db.add(Transaction(
            statement_id=stmt.id, account_id=acc.id,
            date=p["date"], description=p["description"],
            amount=p["amount"], type=p["type"],
        ))
    # Inject one extra phantom transaction that's not in the PDF.
    db.add(Transaction(
        statement_id=stmt.id, account_id=acc.id,
        date="2026-03-15", description="EXTRA INSERTED FOR TEST",
        amount=99.99, type="debit",
    ))
    db.commit()

    result = reconcile_statement(stmt.id, db)
    assert result.ok is False
    assert "row count mismatch" in (result.note or "")


def test_reconcile_maybank_ending_balance_mismatch_flags(db, tmp_path, monkeypatch):
    # Use the 2018 sample but corrupt the ENDING BALANCE line so that the
    # explicit ending-balance cross-check fails (per-row arithmetic still ok).
    import fitz
    from app.services.parsers.maybank import MaybankParser

    sample_path = Path(__file__).parent.parent / "sample_data" / "maybank_2018_sample.txt"
    sample_text = sample_path.read_text().replace(
        "ENDING BALANCE :\n341.52", "ENDING BALANCE :\n999.99"
    )

    pdf_path = tmp_path / "maybank_ending_corrupt.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 555, 800), sample_text, fontsize=8, fontname="cour")
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)

    acc = Account(name="Maybank Savings", bank="maybank", type="bank")
    db.add(acc); db.commit()

    parser = MaybankParser()
    # Parse from the ORIGINAL sample text (not the corrupted PDF) so DB rows
    # match the per-row arithmetic. The reconciler reads the corrupted PDF
    # and detects that ENDING BALANCE doesn't match the running balance.
    parsed = parser.parse(sample_path.read_text())

    stmt = Statement(
        file_hash="maybank-ending-corrupt-hash",
        bank="maybank",
        source="email",
        filename="maybank_ending_corrupt.pdf",
        period_month=parser.extract_period_month(sample_text) or "",
        file_path="maybank_ending_corrupt.pdf",
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
    assert result.ok is False
    assert "ending" in (result.note or "").lower()
```

- [ ] **Step 2: Run the new tests — they must fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v -k maybank`
Expected: FAIL — the Maybank dispatch arm doesn't exist yet, so reconciliation returns `ok=True, note="unknown bank format"`, which doesn't match the assertions.

- [ ] **Step 3: Add Maybank constants and helpers to `backend/app/services/reconciler.py`**

Locate the existing format-marker constants near the top of the file (`_NEW_FORMAT_MARKER = "TNG WALLET TRANSACTION HISTORY"` etc.). Add right after `_AEON_MARKER`:

```python
_MAYBANK_MARKER = "Malayan Banking Berhad"
_MAYBANK_MARKER_2 = "URUSNIAGA AKAUN"
```

Then add these helpers after `_extract_rows_from_aeon_credit` (near the end of the helper section, before the "Public entry point" header):

```python
_MAYBANK_DATE_LINE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
_MAYBANK_SIGNED_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}[+-]$")
_MAYBANK_BALANCE_RE = re.compile(r"^[\d,]+\.\d{2}$")
_MAYBANK_END_MARKERS = (
    "ENDING BALANCE :",
    "TARIKH PENYATA",
    "TERMS AND CONDITION",
    "Malayan Banking Berhad",
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
```

- [ ] **Step 4: Add the Maybank dispatch arm to `reconcile_statement`**

Find the existing dispatch block in `reconcile_statement`:

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

Replace it with:

```python
    text = "".join(p.get_text() for p in doc)
    aeon_headers: dict | None = None
    maybank_balances: dict | None = None
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
    else:
        doc.close()
        return ReconcileResult(ok=True, note="unknown bank format")
    doc.close()
```

- [ ] **Step 5: Add the Maybank statement-level check after the count check**

Find the existing checks section (after `r = _check_count(...)` and the AEON-specific block). Insert a Maybank-specific block right BEFORE the existing `has_balance = any(row.get("balance") is not None for row in rows)` block. The full updated checks section becomes:

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
    # always + ENDING BALANCE :  in 2018-era statements only. Run the existing
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

- [ ] **Step 6: Run the Maybank reconciler tests — they must pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v -k maybank`
Expected: 4 passed.

- [ ] **Step 7: Run the full reconciler test suite + full backend suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v`
Expected: all reconciler tests pass (TnG and AEON ones still green).

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/reconciler.py backend/tests/test_reconciler.py
git commit -m "feat(ringgit): reconciler maybank dispatch with per-row + statement checks"
```

---

## Task 4: Real-fixture reconciler test for Maybank

**Files:**
- Modify: `backend/tests/test_reconciler.py` (append one test)
- Stage (gitignored): `backend/tests/fixtures/real/maybank_savings.pdf`

This task validates the parser + reconciler against a real Maybank PDF. The fixture is not committed (the directory is gitignored). The password is read from the configured `SENDER_PASSWORDS["m2u@stmts.maybank2u.com.my"]` rather than hardcoded — keeps the password out of the test file.

- [ ] **Step 1: Append the real-fixture test to `backend/tests/test_reconciler.py`**

Append after the synthetic Maybank tests added in Task 3:

```python
@pytest.mark.skipif(
    not _MAYBANK_FIXTURE_PATH.exists(),
    reason=f"real fixture {_MAYBANK_FIXTURE_NAME} not present",
)
def test_reconcile_real_maybank_savings_passes(db, monkeypatch, tmp_path):
    import fitz
    from app.config import SENDER_PASSWORDS
    from app.services.parsers.maybank import MaybankParser

    password = SENDER_PASSWORDS.get("m2u@stmts.maybank2u.com.my")
    if not password:
        pytest.skip("PDF_PASSWORD_MAYBANK not configured")

    staged = tmp_path / _MAYBANK_FIXTURE_NAME
    shutil.copy(_MAYBANK_FIXTURE_PATH, staged)
    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)
    # SENDER_PASSWORDS is already populated correctly from the env at import
    # time; no monkeypatching needed.

    acc = Account(name="Maybank Savings", bank="maybank", type="bank")
    db.add(acc); db.commit()

    doc = fitz.open(str(staged))
    if doc.is_encrypted:
        doc.authenticate(password)
    text = "".join(p.get_text() for p in doc)
    doc.close()
    parser = MaybankParser()
    parsed = parser.parse(text)
    assert len(parsed) > 0, "parser produced 0 transactions on real Maybank fixture"

    stmt = Statement(
        file_hash="maybank-real-test-hash",
        bank="maybank",
        source="email",
        filename=_MAYBANK_FIXTURE_NAME,
        period_month=parser.extract_period_month(text) or "",
        file_path=_MAYBANK_FIXTURE_NAME,
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
    assert result.ok, f"real Maybank reconciliation failed: {result.note} (checks_run={result.checks_run})"
    assert "count" in result.checks_run
    assert "statement" in result.checks_run
    assert "per_row" in result.checks_run
```

- [ ] **Step 2: Stage one real Maybank PDF as the test fixture**

Pick a recent, single-page-or-small statement (less likely to surface multi-page edge cases on the first run). The user's most recent Maybank PDF in the DB is `847673614_20260331_7244.pdf`:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    row = conn.execute(text(\"SELECT file_path FROM statements WHERE filename='847673614_20260331_7244.pdf' LIMIT 1\")).first()
print(row[0] if row else 'not found')
"
```

Expected: prints a path like `fetched_pdfs\wengyeowyeap_gmail_com\unknown_unknown_693374fb.pdf`.

Then copy that file to the fixture location:

```bash
mkdir -p backend/tests/fixtures/real && cp "backend/$(./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    row = conn.execute(text(\"SELECT file_path FROM statements WHERE filename='847673614_20260331_7244.pdf' LIMIT 1\")).first()
print(row[0].replace(chr(92), '/') if row else '')
")" backend/tests/fixtures/real/maybank_savings.pdf
```

(The `chr(92)` substitution converts Windows backslashes to forward slashes for bash. If the cp fails on path issues, do it manually using PowerShell `Copy-Item` and the path printed by the first command.)

Expected: silent success. The directory is gitignored (existing `.gitignore` rule), so the file stays local-only.

- [ ] **Step 3: Run the real-fixture test — it must PASS (not skip)**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_reconcile_real_maybank_savings_passes -v`
Expected: 1 passed. If it skips, the fixture wasn't staged correctly — re-do Step 2.

If it FAILS (not skips), the failure is real — investigate. Likely culprits:
- Multi-page page-header repeats getting eaten as detail lines (extend `_MAYBANK_END_MARKERS` or filter detail lines)
- A type label that's not the first line after the date (real fixtures may have different layout)
- Regex tolerance issues with whitespace between BEGINNING BALANCE and the amount

If failures are real-fixture-specific and not covered by synthetic tests, add a regression test for the specific issue, then fix.

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_reconciler.py
git commit -m "test(ringgit): real-fixture reconciler test for maybank savings"
```

(The fixture PDF itself is gitignored and stays local.)

---

## Task 5: Reprocess script for Maybank statements

**Files:**
- Create: `backend/scripts/reprocess_maybank.py`

- [ ] **Step 1: Create the script**

Create `backend/scripts/reprocess_maybank.py`:

```python
"""Re-parse all Maybank savings statements through the current parser,
replacing every existing Maybank transaction in-place. Idempotent — running
it twice produces the same end state. Use after Maybank parser fixes.

Candidate statements: bank in ('unknown', 'maybank') AND filename matches
the user's Maybank account suffix `_7244.pdf` OR contains "maybank".
Each candidate is content-confirmed by `MaybankParser.can_parse(text)`
before being processed, so any false-positive filename match is skipped.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reprocess_maybank.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from sqlalchemy import create_engine, or_
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

    # Step 1: ensure the maybank account exists (create if missing — first
    # reprocess is the canonical creation point if fetch hasn't yet).
    maybank_account = db.query(Account).filter_by(bank="maybank").first()
    if not maybank_account:
        maybank_account = Account(
            name="Maybank Savings",
            bank="maybank",
            type="bank",
            account_number="maybank-savings",
        )
        db.add(maybank_account); db.commit()
        print(f"created Maybank account id={maybank_account.id}")

    # Step 2: delete existing Maybank transactions (defensive against re-runs).
    deleted = db.query(Transaction).filter_by(account_id=maybank_account.id).delete()
    db.commit()
    print(f"deleted {deleted} existing Maybank transactions")

    # Step 3: find candidate statements via filename heuristic.
    stmts = (
        db.query(Statement)
        .filter(Statement.bank.in_(["unknown", "maybank"]))
        .filter(or_(
            Statement.filename.like("%_7244.pdf"),
            Statement.filename.like("%maybank%"),
        ))
        .order_by(Statement.id)
        .all()
    )
    print(f"reprocessing {len(stmts)} Maybank candidate statements")

    existing_keys: set[tuple] = set()
    inserted = 0
    skipped = 0
    extraction_failures = 0
    detection_failures = 0

    for stmt in stmts:
        fp = Path(stmt.file_path)
        text = None
        # Try without password first (some PDFs not encrypted), then try every
        # configured password — same as TnG/AEON reprocess scripts.
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

        # Content-confirm via parser registry (rejects false-positive filenames).
        parser = registry.detect_bank(text)
        if parser is None or parser.bank_id != "maybank":
            detection_failures += 1
            continue

        parsed = parser.parse(text)
        period_month = parser.extract_period_month(text) or ""
        if period_month and stmt.period_month != period_month:
            stmt.period_month = period_month
        if stmt.bank != "maybank":
            stmt.bank = "maybank"

        for p in parsed:
            # No external_reference for Maybank; broad-key dedup only.
            key = (p["date"], p["amount"], p["type"], p["description"])
            if key in existing_keys:
                skipped += 1; continue
            existing_keys.add(key)
            cat_id = categorizer.categorize(p["description"])
            if cat_id is None and uncat:
                cat_id = uncat.id
            db.add(Transaction(
                statement_id=stmt.id, account_id=maybank_account.id,
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

Run: `cd backend && ./.venv/Scripts/python.exe scripts/reprocess_maybank.py`
Expected: prints `created Maybank account id=<N>` (if first run) OR no creation line, `deleted 0 existing Maybank transactions` (or N if re-running), `reprocessing 61 Maybank candidate statements`, `inserted: <several thousand>` (61 statements × ~30-50 tx each = ~1800-3000), `skipped (dedup): <small>`, `extraction failures: 0`, `detection failures: 0`.

If `extraction failures` is non-zero: a candidate PDF couldn't be opened or had no extractable text. Print which one and investigate.

If `detection failures` is non-zero: a candidate filename matched the heuristic but the content isn't actually Maybank (e.g., a different bank's PDF that happened to end in `_7244.pdf`). Acceptable — they're correctly skipped.

- [ ] **Step 3: Verify final state**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    total = conn.execute(text(\"SELECT COUNT(*) FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE bank='maybank')\")).scalar()
    stmt_maybank = conn.execute(text(\"SELECT COUNT(*) FROM statements WHERE bank='maybank'\")).scalar()
    stmt_unknown = conn.execute(text(\"SELECT COUNT(*) FROM statements WHERE bank='unknown'\")).scalar()
    print(f'Maybank transactions: {total}')
    print(f'Statements with bank=maybank: {stmt_maybank} (expect 61)')
    print(f'Statements with bank=unknown: {stmt_unknown} (expect ~9 — the AEON VP ones plus any non-Maybank misc)')
"
```

Expected: `Statements with bank=maybank: 61`. `Statements with bank=unknown` should drop from ~70 down to ~9 (the 8 AEON VP statements + any misc). Maybank transactions count depends on actual data.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/reprocess_maybank.py
git commit -m "feat(ringgit): scripts/reprocess_maybank.py for maybank savings statements"
```

---

## Task 6: Backfill reconciliation flag + manual smoke

**Files:**
- None modified

This task uses the existing `backend/scripts/reconcile_existing.py` (committed previously) — no new code.

- [ ] **Step 1: Run the backfill script**

Run: `cd backend && ./.venv/Scripts/python.exe scripts/reconcile_existing.py`
Expected: prints `reconciling <N> statements` (the same total as before, ~71). New Maybank statements are now reconciled; counts should reflect that.

- [ ] **Step 2: Inspect Maybank-specific reconciliation results**

Run:

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///./ringgit.db')
with engine.connect() as conn:
    rows = conn.execute(text(\"SELECT id, period_month, filename, needs_review, reconciliation_note FROM statements WHERE bank='maybank' ORDER BY id\")).fetchall()
    flagged = [r for r in rows if r[3]]
    print(f'Total Maybank statements: {len(rows)}')
    print(f'Flagged needs_review: {len(flagged)}')
    print()
    print('Flagged statements:')
    for r in flagged:
        print(f'  id={r[0]} period={r[1]} file={r[2]}')
        print(f'    note={(r[4] or \"\")[:160]}')
"
```

Expected: Some Maybank statements may flag — single digits to low double digits is acceptable. Common false-positive sources to investigate manually:
- Multi-page statements where page-header repeats leak into detail lines (look for repeated header tokens in description; if confirmed, extend the parser's filter logic)
- Old-format statements with unusual GST line shapes
- Statements with adjustment / interest / charge entries that have zero amounts or unusual sign conventions

For each flagged statement, open the PDF (`fitz.open` + `doc.authenticate`) and visually verify whether the reconciler's flag is a real parser bug vs an acceptable edge case.

- [ ] **Step 3: Final full-suite check**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 4: No commit**

This task is verification-only. No code changed.

---

## Self-review

**Spec coverage:** each section of `2026-05-02-maybank-savings-parser-design.md` is covered:
- Phase 1 parser rewrite (both 2026 and 2018 formats, anchor-based) → Tasks 1, 2.
- Phase 1 reconciler dispatch + per-row + statement-level checks (with optional ENDING BALANCE cross-check) → Task 3.
- Real-fixture validation → Task 4.
- Phase 2 reprocess script → Task 5.
- Backfill via existing script → Task 6.
- Tests for `can_parse` strictness (rejects just "MAYBANK" word, rejects AEON, rejects TnG), 2018 GST line tolerance, multi-line description joining, century inference, BEGINNING/ENDING balance skipping → all in Tasks 2-4.
- Out-of-scope items (Maybank credit card / current account, find_tables for Maybank, OCR, generic config externalization, GST as separate field) → correctly absent from the plan.

**Placeholder scan:** no TBD/TODO markers. Every step has either concrete code, concrete content, or a concrete command with expected output. The only soft language is `"<several thousand>"` for the reprocess insert count and `"single digits to low double digits"` for the expected flagged count — these are estimates of operational reality, not placeholders, and the actual numbers are not load-bearing.

**Type consistency:**
- `MaybankParser` class name and `bank_id="maybank"` consistent across Tasks 2, 3, 4, 5.
- `ReconcileResult` shape (`ok`, `note`, `checks_run`) used identically across Tasks 3 and 4 (matches existing definition).
- `_MAYBANK_MARKER` ("Malayan Banking Berhad"), `_MAYBANK_MARKER_2` ("URUSNIAGA AKAUN"), `_extract_maybank_balances`, `_extract_rows_from_maybank` defined once in Task 3 and consumed only by `reconcile_statement` in the same task.
- `maybank_balances` local variable shape `{"beginning": float, "ending": float | None}` consistent between extractor and consumer.
- Sign convention `+ = credit, - = debit` consistent across parser (Task 2) and reconciler row extractor (Task 3).
- The reprocess script (Task 5) uses the parser's `bank_id="maybank"` for the post-parse content check — matches.
- `Account.type="bank"` used consistently in Tasks 3, 4, 5 (matches the convention used by `_seed_tng_account` for `type="ewallet"` and AEON for `type="credit_card"` — each parser picks an account type appropriate to the financial product).
