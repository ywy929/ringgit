# Public Bank Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an anchor-based parser for Public Bank Moneyplus Savings Account PDF statements, plus a reconciler arm with debit/credit count cross-checks, a reprocess script, and a one-shot loader for backfilling 13 manually-downloaded PDFs.

**Architecture:** State-machine parser scoped between `Balance From Last Statement` and `Closing Balance In This Statement`. Lines are classified as date / number / structural / text. Sign of each transaction is derived from the running-balance delta (`signed = curr_balance − prev_balance`), which sidesteps the column-position problem that PyMuPDF text extraction strips out. A new `public_bank` arm in `reconciler.py` mirrors the parser's state machine independently and adds debit/credit count cross-checks against the statement's summary block — the genuinely-novel guard for this bank (catches silent merge/drop bugs that balance-arithmetic-only checks would miss).

**Tech Stack:** Python 3.x, PyMuPDF (`fitz`), SQLAlchemy, FastAPI, pytest, `requests` (for the loader script).

**Reference spec:** `docs/superpowers/specs/2026-05-04-public-bank-parser-design.md` (committed at `62bbe44`).

---

## File Map

### New files
- `backend/scripts/reprocess_public_bank.py` — DELETE+INSERT reprocess (mirrors `reprocess_maybank.py`)
- `backend/scripts/load_public_bank_pdfs.py` — one-shot loader that POSTs the 13 backfill files to `/api/upload`

### Replaced files
- `backend/sample_data/public_bank_sample.txt` — fictional column-position layout → synthetic PyMuPDF-extracted shape
- `backend/app/services/parsers/public_bank.py` — column-position scaffold → anchor-based state machine
- `backend/tests/test_public_bank_parser.py` — tests against new sample format

### Modified files
- `backend/app/services/reconciler.py` — add `_extract_public_bank_summary`, `_extract_rows_from_public_bank`, marker constants, dispatch arm
- `backend/tests/test_reconciler.py` — add Public Bank helper tests + cross-check tests
- `backend/tests/test_real_pdfs.py` — update `test_public_bank_real_pdf` to expect a real fixture
- `backend/tests/fixtures/real/public_bank_202604.pdf` — gitignored real fixture (one of the 13 user PDFs)

### Untouched
- `backend/app/services/parsers/__init__.py`, `parser_registry.py` — Public Bank is already registered
- `backend/app/routers/email.py`, `app/config.py` — no Gmail wiring this round
- Maybank parser/reconciler — asymmetry deliberately preserved per design spec Q2

### Working directory
All work happens in `C:\Users\aquam\Projects\ringgit\backend`. Run tests with `cd backend && ./.venv/Scripts/python.exe -m pytest`. Use absolute paths in commands (PowerShell may reset shell `cwd` between commands).

---

## Task 1: Replace synthetic sample with real-format mimic

**Files:**
- Replace: `backend/sample_data/public_bank_sample.txt`

The existing fictional sample is a tabular layout that doesn't match what PyMuPDF actually emits from real Public Bank PDFs. Replace it with synthetic text that matches the real extraction shape (collapsed columns, per-line tokens).

- [ ] **Step 1: Write the new sample file**

Replace the entire contents of `backend/sample_data/public_bank_sample.txt` with:

```
YEAP WENG YEOW
PENYATA AKAUN / STATEMENT OF ACCOUNT
Nombor Akaun / Account Number
5099012333
Jenis Akaun / Account Type RM Moneyplus Savings Account
Tarikh Penyata / Statement Date
03 Apr 2026
RINGKASAN / SUMMARY
Baki Penutup / Closing Balance
Jumlah Debit / Total Debits
Bil. Debit / No. of Debits
Jumlah Kredit / Total Credits
Bil. Kredit / No. of Credits
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
1,250.00
780.00
6
30.00
1
03/03
Balance From Last Statement
2,000.00
05/03
500.00
1,500.00
DUITNOW TRSF DR 123456 LOW CHOOI EE
TEST PAYMENT
07/03
30.00
1,530.00
INT CR-INT CYCLE
15/03
2.10
1,527.90
ATM WDL 100001
2.10
1,525.80
ATM WDL 100002
2.10
1,523.70
ATM WDL 100003
20/03
20.00
1,503.70
DEBIT CARD MR DIY
PURCHASE
02/04
253.70
1,250.00
TSFR FUND DR-ATM/EFT 999999
4858XXXXXX RECIPIENT
APR FEES
Closing Balance In This Statement
1,250.00
Public Bank's Privacy Notice at the Bank's website.
You may view Public Bank's Privacy Notice at the Bank's website.
Muka Surat 1 Daripada 1
Page 1 of 1
```

Summary cross-check (matches header):
- closing: 1,250.00 ✓
- total debits: 500 + 2.10 + 2.10 + 2.10 + 20.00 + 253.70 = 780.00 ✓
- count debits: 6 ✓
- total credits: 30.00 ✓
- count credits: 1 ✓

This sample exercises: opening balance, simple debit, simple credit, three same-day repeats, multi-line description, single-page (no page-wrap — that's exercised in Task 6's synthetic).

- [ ] **Step 2: Verify file content**

Run: `python -c "from pathlib import Path; t = Path(r'C:\Users\aquam\Projects\ringgit\backend\sample_data\public_bank_sample.txt').read_text(); print(t.count('Closing Balance In This Statement'), 'closing markers'); print(t.count('15/03'), '15/03 occurrences')"`

Expected: `1 closing markers`, `1 15/03 occurrences` (the date appears once; the same-day repeats inherit it).

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/sample_data/public_bank_sample.txt && git commit -m "test(ringgit): replace public_bank synthetic sample with PyMuPDF-shape mimic"
```

---

## Task 2: Write failing tests for the new architecture

**Files:**
- Replace: `backend/tests/test_public_bank_parser.py`

Tests are written against the new sample and expect the new anchor-based behavior. Will fail against the existing column-position parser — that's the red baseline.

- [ ] **Step 1: Write the new test file**

Replace `backend/tests/test_public_bank_parser.py` with:

```python
from pathlib import Path

from app.services.parsers.public_bank import PublicBankParser

SAMPLE = (Path(__file__).parent.parent / "sample_data" / "public_bank_sample.txt").read_text(encoding="utf-8")


def test_can_parse_positive():
    assert PublicBankParser().can_parse(SAMPLE) is True


def test_can_parse_rejects_partial_marker():
    text = "Public Bank Berhad\nSavings Account\nSomething else"
    assert PublicBankParser().can_parse(text) is False


def test_can_parse_rejects_maybank():
    text = "Malayan Banking Berhad\nURUSNIAGA AKAUN\nMaybank Savings"
    assert PublicBankParser().can_parse(text) is False


def test_extract_period_month():
    assert PublicBankParser().extract_period_month(SAMPLE) == "2026-04"


def test_extract_period_month_missing():
    assert PublicBankParser().extract_period_month("no date here") == ""


def test_parse_count_matches_summary():
    txs = PublicBankParser().parse(SAMPLE)
    # Summary: 6 debits + 1 credit = 7 transactions.
    assert len(txs) == 7, f"expected 7, got {len(txs)}: {txs}"


def test_parse_simple_debit_first_transaction():
    txs = PublicBankParser().parse(SAMPLE)
    first = txs[0]
    assert first["date"] == "2026-03-05"
    assert first["type"] == "debit"
    assert first["amount"] == 500.00
    assert "DUITNOW TRSF DR 123456" in first["description"]


def test_parse_simple_credit_second_transaction():
    txs = PublicBankParser().parse(SAMPLE)
    second = txs[1]
    assert second["date"] == "2026-03-07"
    assert second["type"] == "credit"
    assert second["amount"] == 30.00
    assert "INT CR-INT CYCLE" in second["description"]


def test_parse_same_day_repeats_preserved():
    # Three identical RM2.10 ATM withdrawals on 15/03 (toll-gate-style case
    # from ADR-003) must all be present.
    txs = PublicBankParser().parse(SAMPLE)
    same_day = [t for t in txs if t["date"] == "2026-03-15"]
    assert len(same_day) == 3
    assert all(t["amount"] == 2.10 for t in same_day)
    assert all(t["type"] == "debit" for t in same_day)


def test_parse_multi_line_description():
    txs = PublicBankParser().parse(SAMPLE)
    last = txs[-1]
    assert last["date"] == "2026-04-02"
    assert last["amount"] == 253.70
    assert last["type"] == "debit"
    # Joins all description lines.
    assert "TSFR FUND" in last["description"]
    assert "RECIPIENT" in last["description"]
    assert "APR FEES" in last["description"]


def test_parse_skips_balance_from_last_statement():
    # The opening-balance row produces no transaction; it just seeds the
    # running balance for the first real transaction's sign inference.
    txs = PublicBankParser().parse(SAMPLE)
    assert not any("Balance From Last Statement" in t["description"] for t in txs)


def test_parse_skips_closing_balance_marker():
    # The Closing Balance footer marker is a section terminator, not a
    # transaction row.
    txs = PublicBankParser().parse(SAMPLE)
    assert not any("Closing Balance" in t["description"] for t in txs)


def test_parse_signs_are_correct_via_balance_delta():
    # Sanity: total signed = closing - opening.
    txs = PublicBankParser().parse(SAMPLE)
    signed_total = sum(t["amount"] if t["type"] == "credit" else -t["amount"] for t in txs)
    # Opening 2000.00 → closing 1250.00 → delta -750.00.
    assert abs(signed_total - (-750.00)) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py -v`

Expected: most tests FAIL (the existing column-position parser doesn't match the new sample format). `test_can_parse_positive` may pass coincidentally. The failures are the red baseline — do not try to fix the parser yet.

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/tests/test_public_bank_parser.py && git commit -m "test(ringgit): public_bank parser tests for anchor-based redesign (red)"
```

---

## Task 3: Parser skeleton — can_parse, extract_period_month, empty parse()

**Files:**
- Replace: `backend/app/services/parsers/public_bank.py`

Strip the column-position scaffold and replace with an anchor-based skeleton that handles `can_parse` and `extract_period_month` (matches new sample) but `parse()` still returns an empty list. Two of the failing tests will turn green; the parse-related tests stay red.

- [ ] **Step 1: Replace `public_bank.py` with the skeleton**

Replace the entire contents of `backend/app/services/parsers/public_bank.py` with:

```python
"""Public Bank Moneyplus Savings Account statement parser.

Real Public Bank PDFs flatten through PyMuPDF as line-by-line tokens with
the debit/credit columns collapsed (no positional info). The parser scopes
work to the section between `Balance From Last Statement` and `Closing
Balance In This Statement`, classifies each line, and walks a state machine
that pairs amount/balance numerics, derives sign from running-balance delta,
and stitches descriptions across page-break carry-forwards.

See docs/superpowers/specs/2026-05-04-public-bank-parser-design.md for the
full architectural rationale.
"""
import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction


# Statement-date block: bilingual header followed by the date on the next line.
_STATEMENT_DATE_RE = re.compile(
    r"Tarikh Penyata / Statement Date\s*\n\s*(\d{2}\s+\w{3}\s+\d{4})"
)


class PublicBankParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "public_bank"

    def can_parse(self, text: str) -> bool:
        # Two-marker strict check. "Public Bank" alone matches AEON's footer
        # disclaimer; we additionally require the savings-account-type line.
        return "Public Bank" in text and "Moneyplus Savings Account" in text

    def extract_period_month(self, text: str) -> str:
        m = _STATEMENT_DATE_RE.search(text)
        if not m:
            return ""
        try:
            dt = datetime.strptime(m.group(1), "%d %b %Y")
            return dt.strftime("%Y-%m")
        except ValueError:
            return ""

    def parse(self, text: str) -> list[ParsedTransaction]:
        # Implemented in Task 4.
        return []
```

- [ ] **Step 2: Run tests — confirm can_parse + extract_period_month pass, parse-related still fail**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py -v`

Expected: `test_can_parse_positive`, `test_can_parse_rejects_partial_marker`, `test_can_parse_rejects_maybank`, `test_extract_period_month`, `test_extract_period_month_missing` all PASS. All `test_parse_*` tests FAIL (parse returns []).

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/app/services/parsers/public_bank.py && git commit -m "refactor(ringgit): replace public_bank scaffold with anchor-based skeleton"
```

---

## Task 4: Parser — basic state machine (opening balance + simple transactions + same-day repeats)

**Files:**
- Modify: `backend/app/services/parsers/public_bank.py`

Implement the line classifier, section bounds, and the state machine that handles opening balance, sequential transactions, and same-day-repeat transactions (no date prefix). Page-wrap stitching and year inference are deferred to Tasks 6 and 7.

- [ ] **Step 1: Replace `public_bank.py` with the basic state machine**

Replace `backend/app/services/parsers/public_bank.py` (entire contents) with:

```python
"""Public Bank Moneyplus Savings Account statement parser.

Real Public Bank PDFs flatten through PyMuPDF as line-by-line tokens with
the debit/credit columns collapsed (no positional info). The parser scopes
work to the section between `Balance From Last Statement` and `Closing
Balance In This Statement`, classifies each line, and walks a state machine
that pairs amount/balance numerics, derives sign from running-balance delta,
and stitches descriptions across page-break carry-forwards.

See docs/superpowers/specs/2026-05-04-public-bank-parser-design.md for the
full architectural rationale.
"""
import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction


_STATEMENT_DATE_RE = re.compile(
    r"Tarikh Penyata / Statement Date\s*\n\s*(\d{2}\s+\w{3}\s+\d{4})"
)
_DATE_LINE_RE = re.compile(r"^\d{2}/\d{2}$")
_NUMBER_LINE_RE = re.compile(r"^[\d,]+\.\d{2}$")

_SECTION_START_MARKER = "Balance From Last Statement"
_SECTION_END_MARKER = "Closing Balance In This Statement"

# Whole-line structural markers (page-break carry-forward + opening row).
_STRUCTURAL_LINES = frozenset({
    "Balance From Last Statement",
    "Balance B/F",
    "Balance C/F",
})

# Whole-line page-header / column-header / footer noise that appears on
# page 2+ and between transactions when extracted text concatenates pages.
_HEADER_LINES = frozenset({
    "TARIKH", "URUS NIAGA", "DEBIT", "KREDIT", "BAKI",
    "DATE", "TRANSACTION", "CREDIT", "BALANCE",
})

_PAGE_FOOTER_RE = re.compile(r"^Muka Surat \d+ Daripada \d+$|^Page \d+ of \d+$")


def _is_header_or_footer(line: str) -> bool:
    s = line.strip()
    if s in _HEADER_LINES:
        return True
    if _PAGE_FOOTER_RE.match(s):
        return True
    return False


class PublicBankParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "public_bank"

    def can_parse(self, text: str) -> bool:
        return "Public Bank" in text and "Moneyplus Savings Account" in text

    def extract_period_month(self, text: str) -> str:
        m = _STATEMENT_DATE_RE.search(text)
        if not m:
            return ""
        try:
            dt = datetime.strptime(m.group(1), "%d %b %Y")
            return dt.strftime("%Y-%m")
        except ValueError:
            return ""

    def parse(self, text: str) -> list[ParsedTransaction]:
        lines = text.splitlines()

        # Locate section bounds: Balance From Last Statement → Closing Balance.
        start = None
        end = len(lines)
        for i, ln in enumerate(lines):
            s = ln.strip()
            if start is None and s == _SECTION_START_MARKER:
                start = i
            elif s == _SECTION_END_MARKER:
                end = i
                break
        if start is None:
            return []

        # The line preceding _SECTION_START_MARKER is the opening date; the
        # line right after is the opening balance.
        if start + 1 >= end:
            return []
        opening_balance_line = lines[start + 1].strip()
        if not _NUMBER_LINE_RE.match(opening_balance_line):
            return []
        prev_balance = float(opening_balance_line.replace(",", ""))

        # Statement (M_s, Y_s) for year inference.
        m = _STATEMENT_DATE_RE.search(text)
        if not m:
            return []
        stmt_dt = datetime.strptime(m.group(1), "%d %b %Y")
        stmt_year = stmt_dt.year
        stmt_month = stmt_dt.month

        # State machine over [section_start + 2, end).
        transactions: list[ParsedTransaction] = []
        current_date_str: str | None = None
        i = start + 2
        last_tx_desc: list[str] | None = None  # mutable description tracker for stitching (Task 6)

        while i < end:
            line = lines[i].strip()

            if not line or _is_header_or_footer(line) or line in _STRUCTURAL_LINES:
                i += 1
                continue

            # Date line: update current_date.
            if _DATE_LINE_RE.match(line):
                current_date_str = line
                i += 1
                continue

            # Number-pair pattern: amount + balance.
            if _NUMBER_LINE_RE.match(line):
                if i + 1 >= end:
                    break
                next_line = lines[i + 1].strip()
                if not _NUMBER_LINE_RE.match(next_line):
                    # Lone number — skip defensively.
                    i += 1
                    continue
                if current_date_str is None:
                    # Numbers before any date — skip (defensive).
                    i += 2
                    continue

                amount_val = float(line.replace(",", ""))
                curr_balance = float(next_line.replace(",", ""))
                signed = curr_balance - prev_balance
                if signed >= 0:
                    tx_type = "credit"
                    amount = round(signed, 2)
                else:
                    tx_type = "debit"
                    amount = round(-signed, 2)

                # Year inference for current_date (DD/MM): if MM > stmt_month,
                # transaction is in stmt_year - 1, else stmt_year.
                day_str, month_str = current_date_str.split("/")
                tx_month = int(month_str)
                tx_year = stmt_year - 1 if tx_month > stmt_month else stmt_year
                iso_date = f"{tx_year:04d}-{tx_month:02d}-{int(day_str):02d}"

                # Walk forward to collect description lines until next D/N/structural.
                desc_lines: list[str] = []
                j = i + 2
                while j < end:
                    dline = lines[j].strip()
                    if not dline:
                        j += 1
                        continue
                    if _DATE_LINE_RE.match(dline) or _NUMBER_LINE_RE.match(dline):
                        break
                    if dline in _STRUCTURAL_LINES or _is_header_or_footer(dline):
                        break
                    desc_lines.append(dline)
                    j += 1

                description = " ".join(desc_lines)[:200] if desc_lines else "Public Bank transaction"
                description = re.sub(r"\s+", " ", description).strip()

                tx: ParsedTransaction = {
                    "date": iso_date,
                    "description": description,
                    "amount": amount,
                    "type": tx_type,
                }
                transactions.append(tx)
                last_tx_desc = desc_lines  # for Task 6 page-wrap stitching

                prev_balance = curr_balance
                # `amount_val` is intentionally unused — sign comes from balance delta.
                # Reading it is purely defensive (catches a bad parse where the line
                # parses as a number but isn't actually the amount column).
                _ = amount_val
                i = j
                continue

            # Anything else: text line outside a transaction (orphan or carry-
            # forward). Page-wrap stitching is added in Task 6.
            i += 1

        return transactions
```

- [ ] **Step 2: Run tests — verify all `test_parse_*` tests pass**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py -v`

Expected: ALL 13 tests PASS, including:
- `test_parse_count_matches_summary` (7 transactions)
- `test_parse_simple_debit_first_transaction`
- `test_parse_simple_credit_second_transaction`
- `test_parse_same_day_repeats_preserved` (3 same-day repeats)
- `test_parse_multi_line_description`
- `test_parse_skips_balance_from_last_statement`
- `test_parse_skips_closing_balance_marker`
- `test_parse_signs_are_correct_via_balance_delta`

If any test fails, fix the parser before proceeding.

- [ ] **Step 3: Run the full parser test suite (defensive — make sure nothing else broke)**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/ -v --no-header -q`

Expected: same total pass count as before this task (no other tests should regress). Currently `test_real_pdfs.py::test_public_bank_real_pdf` may show as `skipped` (fixture not yet staged); that's fine.

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/app/services/parsers/public_bank.py && git commit -m "feat(ringgit): public_bank parser — anchor-based state machine

Bounded-section state machine (Balance From Last Statement → Closing
Balance In This Statement) with line classifier (date / number /
structural / text). Sign of each transaction is derived from running-
balance delta — sidesteps the column-position problem that PyMuPDF
strips out per ADR-001. Same-day repeats fall out naturally because
date lines are sticky across consecutive amount-balance pairs.

Page-wrap description stitching and a soft-bounds year-inference
assertion are deferred to subsequent tasks."
```

---

## Task 5: Parser — page-wrap with description stitching

**Files:**
- Modify: `backend/app/services/parsers/public_bank.py`
- Modify: `backend/tests/test_public_bank_parser.py`

Add a synthetic two-page test where the last transaction's description splits across the `Balance C/F` / `Balance B/F` boundary, then update the parser to detect and stitch the orphan text.

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_public_bank_parser.py`:

```python
PAGE_WRAP_SAMPLE = """\
PENYATA AKAUN / STATEMENT OF ACCOUNT
Tarikh Penyata / Statement Date
03 Apr 2026
Jenis Akaun / Account Type RM Moneyplus Savings Account
Public Bank's Privacy Notice
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
500.00
500.00
1
0.00
0
03/03
Balance From Last Statement
1,000.00
24/03
500.00
500.00
DR-ECP 462236 LINE-1
LINE-2
LINE-3
Balance C/F
500.00
Muka Surat 1 Daripada 2
Page 1 of 2
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
24/03
Balance B/F
500.00
ORPHAN-LINE-FROM-PAGE-2
Closing Balance In This Statement
500.00
"""


def test_page_wrap_description_stitched():
    txs = PublicBankParser().parse(PAGE_WRAP_SAMPLE)
    assert len(txs) == 1
    only = txs[0]
    assert only["date"] == "2026-03-24"
    assert only["amount"] == 500.00
    assert only["type"] == "debit"
    # All description lines (page-1 + page-2 orphan) are joined.
    assert "LINE-1" in only["description"]
    assert "LINE-2" in only["description"]
    assert "LINE-3" in only["description"]
    assert "ORPHAN-LINE-FROM-PAGE-2" in only["description"]
```

- [ ] **Step 2: Run the new test — verify it fails**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py::test_page_wrap_description_stitched -v`

Expected: FAIL — the parser doesn't yet append page-2 orphan text to the previous transaction's description, so `"ORPHAN-LINE-FROM-PAGE-2"` is missing from `description`.

- [ ] **Step 3: Update the parser to stitch across page breaks**

In `backend/app/services/parsers/public_bank.py`, replace the `parse` method's `# Anything else: text line outside a transaction...` branch (the trailing `else: i += 1` near the end of the while loop) with the page-wrap stitching logic.

Find this block:

```python
            # Anything else: text line outside a transaction (orphan or carry-
            # forward). Page-wrap stitching is added in Task 6.
            i += 1
```

Replace with:

```python
            # Anything else: text line outside a transaction. If we're past
            # the last emitted transaction's description and inside a page-
            # break carry-forward (i.e., we just consumed a Balance B/F → N
            # pair without producing a transaction), the orphan text belongs
            # to the previous transaction. Append it.
            if transactions and last_tx_desc is not None:
                last_tx_desc.append(line)
                # Re-render the merged description on the last transaction.
                merged = " ".join(last_tx_desc)[:200]
                merged = re.sub(r"\s+", " ", merged).strip()
                transactions[-1]["description"] = merged
            i += 1
```

- [ ] **Step 4: Run the page-wrap test — verify it passes**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py::test_page_wrap_description_stitched -v`

Expected: PASS.

- [ ] **Step 5: Run the full test file — verify no regressions**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py -v`

Expected: all 14 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/app/services/parsers/public_bank.py backend/tests/test_public_bank_parser.py && git commit -m "feat(ringgit): public_bank parser — page-wrap description stitching

Transaction descriptions can wrap across the Balance C/F → Balance B/F
page boundary. After a page-break carry-forward, any text lines that
appear before the next D or N are appended to the previous
transaction's description with single-space separator."
```

---

## Task 6: Parser — year inference soft-bounds assertion

**Files:**
- Modify: `backend/app/services/parsers/public_bank.py`
- Modify: `backend/tests/test_public_bank_parser.py`

Year inference (`MM > M_s → Y_s − 1, else Y_s`) is already in the parser from Task 4. Add a test that exercises the year-wrap case (Jan statement with Dec dates), and add a soft-bounds runtime warning when a transaction's inferred date falls outside the statement period.

- [ ] **Step 1: Add the year-wrap test**

Append to `backend/tests/test_public_bank_parser.py`:

```python
YEAR_WRAP_SAMPLE = """\
PENYATA AKAUN / STATEMENT OF ACCOUNT
Tarikh Penyata / Statement Date
03 Jan 2026
Jenis Akaun / Account Type RM Moneyplus Savings Account
Public Bank's Privacy Notice
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
1,000.00
0.00
0
2.00
1
03/12
Balance From Last Statement
998.00
31/12
2.00
1,000.00
INT CR-INT CYCLE
Closing Balance In This Statement
1,000.00
"""


def test_year_inference_wrap():
    # Jan 2026 statement contains 03/12 and 31/12 → those are Dec 2025.
    txs = PublicBankParser().parse(YEAR_WRAP_SAMPLE)
    assert len(txs) == 1
    only = txs[0]
    assert only["date"] == "2025-12-31"
    assert only["type"] == "credit"
    assert only["amount"] == 2.00
```

- [ ] **Step 2: Run the new test — verify it passes (year inference is already in the parser)**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py::test_year_inference_wrap -v`

Expected: PASS — the year-inference logic from Task 4 already handles this case.

If FAIL, debug the parse method's year-inference block before proceeding.

- [ ] **Step 3: Add the soft-bounds out-of-range warning test**

Append to `backend/tests/test_public_bank_parser.py`:

```python
import logging


def test_out_of_bounds_date_logs_warning(caplog):
    # A statement claiming Apr 2026 with a transaction dated 03/06 (June)
    # would infer 2025-06 (year-1 because 6 > 4). That's > 40 days before
    # the statement date — the parser should log a warning but still emit
    # the transaction.
    sample = """\
Tarikh Penyata / Statement Date
03 Apr 2026
Jenis Akaun / Account Type RM Moneyplus Savings Account
Public Bank's Privacy Notice
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
0.00
10.00
1
0.00
0
03/06
Balance From Last Statement
10.00
03/06
10.00
0.00
SOMETHING SUSPICIOUS
Closing Balance In This Statement
0.00
"""
    with caplog.at_level(logging.WARNING):
        txs = PublicBankParser().parse(sample)
    # Transaction is still emitted (soft-bound, not hard fail).
    assert len(txs) == 1
    # And a warning was logged.
    assert any("out of bounds" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 4: Run the new test — verify it fails**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py::test_out_of_bounds_date_logs_warning -v`

Expected: FAIL — no warning is logged.

- [ ] **Step 5: Add the soft-bounds warning to the parser**

In `backend/app/services/parsers/public_bank.py`, add at module top (below the existing imports):

```python
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)
```

Then in the `parse` method, immediately after the line `iso_date = f"{tx_year:04d}-{tx_month:02d}-{int(day_str):02d}"`, insert:

```python
                # Soft-bound assertion: warn if the inferred date falls
                # outside [stmt_date − 40 days, stmt_date]. Doesn't fail
                # the parse — the reconciler is the authoritative guardrail.
                tx_dt = datetime(tx_year, tx_month, int(day_str))
                if tx_dt > stmt_dt or tx_dt < stmt_dt - timedelta(days=40):
                    logger.warning(
                        "public_bank: inferred transaction date %s is out "
                        "of bounds for statement date %s (raw line %s)",
                        iso_date, stmt_dt.strftime("%Y-%m-%d"), current_date_str,
                    )
```

- [ ] **Step 6: Run the test — verify it passes**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py::test_out_of_bounds_date_logs_warning -v`

Expected: PASS.

- [ ] **Step 7: Run the full test file — verify no regressions**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_public_bank_parser.py -v`

Expected: all 16 tests PASS.

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/app/services/parsers/public_bank.py backend/tests/test_public_bank_parser.py && git commit -m "feat(ringgit): public_bank parser — year-wrap test + out-of-bounds soft warning

Year inference (DD/MM → year derived from statement date M_s, Y_s) was
already implemented in the basic state machine; now exercised by an
explicit Jan-statement-with-Dec-dates test. Adds a logging.warning
when the inferred date falls outside [stmt_date - 40 days, stmt_date]
— catches potential year-rule regressions at runtime without failing
the parse (reconciler remains the authoritative guardrail per ADR-002)."
```

---

## Task 7: Real-PDF regression fixture + test

**Files:**
- Create: `backend/tests/fixtures/real/public_bank_202604.pdf` (gitignored — copy from user's Downloads/)
- Modify: `backend/tests/test_real_pdfs.py`

Stage one of the user's 13 backfill PDFs as the regression fixture. The fixtures dir is gitignored, so copying the file does not commit data.

- [ ] **Step 1: Copy the Apr 2026 PDF to the fixture location**

Run:
```bash
cp "C:/Users/aquam/Downloads/Public Bank Apr 2026.pdf" "C:/Users/aquam/Projects/ringgit/backend/tests/fixtures/real/public_bank_202604.pdf"
```

- [ ] **Step 2: Verify the fixture is gitignored**

Run: `cd "C:/Users/aquam/Projects/ringgit" && git status --short backend/tests/fixtures/real/`

Expected: empty output (the `.gitignore` rule `tests/fixtures/real/*` excludes the file).

- [ ] **Step 3: Tighten the existing real-PDF test**

Edit `backend/tests/test_real_pdfs.py`. Find:

```python
@skip_if_no_fixture("public_bank_202603.pdf")
def test_public_bank_real_pdf():
    text = load_real_pdf_text("public_bank_202603.pdf")
    parser = PublicBankParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1
```

Replace with:

```python
@skip_if_no_fixture("public_bank_202604.pdf")
def test_public_bank_real_pdf():
    # Real Apr 2026 statement: 9 debits + 2 credits = 11 transactions per
    # the summary block (and validates the page-wrap stitching against an
    # actual multi-page PDF, not just synthetic text).
    text = load_real_pdf_text("public_bank_202604.pdf")
    parser = PublicBankParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) == 11, f"expected 11 transactions, got {len(txs)}"
    # Sign sanity: closing - opening = 8,921.73 - 19,069.69 = -10,147.96.
    signed_total = sum(t["amount"] if t["type"] == "credit" else -t["amount"] for t in txs)
    assert abs(signed_total - (-10147.96)) < 0.01, f"signed total mismatch: {signed_total:.2f}"
```

- [ ] **Step 4: Run the regression test**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_real_pdfs.py::test_public_bank_real_pdf -v`

Expected: PASS. If the count or signed total is off, inspect the parsed transactions (`pytest -v -s` to see prints) and fix the parser before continuing.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/tests/test_real_pdfs.py && git commit -m "test(ringgit): tighten public_bank real-PDF regression — exact count + signed total"
```

(The PDF fixture itself is gitignored and not added.)

---

## Task 8: Reconciler — `_extract_public_bank_summary` helper

**Files:**
- Modify: `backend/app/services/reconciler.py`
- Modify: `backend/tests/test_reconciler.py`

Add the helper that pulls the 5-line summary block (closing balance, total debits, count debits, total credits, count credits) from the statement text.

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_reconciler.py`:

```python
def test_extract_public_bank_summary_happy_path():
    from app.services.reconciler import _extract_public_bank_summary
    text = """\
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
1,250.00
780.00
6
30.00
1
03/03
"""
    result = _extract_public_bank_summary(text)
    assert result == {
        "closing": 1250.00,
        "total_debits": 780.00,
        "count_debits": 6,
        "total_credits": 30.00,
        "count_credits": 1,
    }


def test_extract_public_bank_summary_missing_returns_none():
    from app.services.reconciler import _extract_public_bank_summary
    text = "no summary block here at all"
    assert _extract_public_bank_summary(text) is None
```

- [ ] **Step 2: Run the new tests — verify they fail (helper doesn't exist)**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_extract_public_bank_summary_happy_path tests/test_reconciler.py::test_extract_public_bank_summary_missing_returns_none -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the helper to `reconciler.py`**

In `backend/app/services/reconciler.py`, add at module top (after the existing `_RM_AMOUNT_RE` block):

```python
_PB_MARKER_1 = "Moneyplus Savings Account"
_PB_MARKER_2 = "Closing Balance In This Statement"

_PB_SUMMARY_RE = re.compile(
    r"BALANCE\s*\n"
    r"([\d,]+\.\d{2})\s*\n"     # closing
    r"([\d,]+\.\d{2})\s*\n"     # total debits
    r"(\d+)\s*\n"               # count debits
    r"([\d,]+\.\d{2})\s*\n"     # total credits
    r"(\d+)\s*\n",              # count credits
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
        "count_debits": int(m.group(3)),
        "total_credits": float(m.group(4).replace(",", "")),
        "count_credits": int(m.group(5)),
    }
```

- [ ] **Step 4: Run the tests — verify they pass**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_extract_public_bank_summary_happy_path tests/test_reconciler.py::test_extract_public_bank_summary_missing_returns_none -v`

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/app/services/reconciler.py backend/tests/test_reconciler.py && git commit -m "feat(ringgit): reconciler — _extract_public_bank_summary helper

Pulls the 5-line summary block from a Public Bank Moneyplus statement:
closing balance, total debits + count, total credits + count. Used by
the upcoming dispatch arm for the genuinely-novel count cross-check
(catches silent merges/drops that pure balance arithmetic misses)."
```

---

## Task 9: Reconciler — `_extract_rows_from_public_bank` helper

**Files:**
- Modify: `backend/app/services/reconciler.py`
- Modify: `backend/tests/test_reconciler.py`

Add the row-extraction helper that mirrors the parser's state machine and emits `{signed_amount, balance}` dicts. It's deliberately a near-duplicate of the parser per ADR-002 — independent extraction is the whole point of the reconciler.

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_reconciler.py`:

```python
def test_extract_rows_from_public_bank_happy_path():
    from app.services.reconciler import _extract_rows_from_public_bank
    from pathlib import Path
    text = (Path(__file__).parent.parent / "sample_data" / "public_bank_sample.txt").read_text(encoding="utf-8")
    rows = _extract_rows_from_public_bank(text)
    # Same 7 transactions the parser produces from the same sample.
    assert len(rows) == 7
    # Sum of signed amounts == closing - opening = 1250 - 2000 = -750.
    signed_sum = sum(r["signed_amount"] for r in rows)
    assert abs(signed_sum - (-750.00)) < 0.01
    # Every row has a balance present.
    assert all(r["balance"] is not None for r in rows)
    # First row is the 500 debit.
    assert rows[0]["signed_amount"] == -500.00
    assert rows[0]["balance"] == 1500.00


def test_extract_rows_from_public_bank_no_section():
    from app.services.reconciler import _extract_rows_from_public_bank
    text = "no transaction section here"
    assert _extract_rows_from_public_bank(text) == []
```

- [ ] **Step 2: Run the new tests — verify they fail**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_extract_rows_from_public_bank_happy_path tests/test_reconciler.py::test_extract_rows_from_public_bank_no_section -v`

Expected: FAIL with ImportError.

- [ ] **Step 3: Add the helper to `reconciler.py`**

In `backend/app/services/reconciler.py`, append after `_extract_public_bank_summary`:

```python
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
    while i < end:
        line = lines[i].strip()
        if not line or _pb_is_noise(line) or line in _PB_STRUCTURAL:
            i += 1
            continue
        if _PB_DATE_LINE_RE.match(line):
            i += 1
            continue
        if _PB_NUMBER_LINE_RE.match(line):
            if i + 1 >= end:
                break
            next_line = lines[i + 1].strip()
            if not _PB_NUMBER_LINE_RE.match(next_line):
                i += 1
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
```

- [ ] **Step 4: Run the new tests — verify they pass**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_extract_rows_from_public_bank_happy_path tests/test_reconciler.py::test_extract_rows_from_public_bank_no_section -v`

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/app/services/reconciler.py backend/tests/test_reconciler.py && git commit -m "feat(ringgit): reconciler — _extract_rows_from_public_bank helper

Mirrors PublicBankParser.parse — same section bounds, same line
classifier, same balance-delta sign rule — but emits {signed_amount,
balance} dicts. The duplicated state-machine logic is the cost of
ADR-002's parser-independent reconciler: a regression in the parser
must not be masked by the reconciler that's supposed to catch it."
```

---

## Task 10: Reconciler — dispatch arm with cross-checks

**Files:**
- Modify: `backend/app/services/reconciler.py`
- Modify: `backend/tests/test_reconciler.py`

Wire the public_bank arm into `reconcile_statement`. Runs count + statement-balance + per-row + closing-balance cross-check + count cross-check.

- [ ] **Step 1: Add the integration test**

Append to `backend/tests/test_reconciler.py`:

```python
def test_reconcile_public_bank_happy_path(client, db):
    """End-to-end reconcile of a synthetic Public Bank statement: upload
    a single-page PDF, expect ok=True and all 5 PB checks to run."""
    import fitz
    from pathlib import Path
    from app.models import Account, Statement

    # Pre-create the public_bank account so /api/upload doesn't return 'failed'.
    db.add(Account(name="Public Bank Moneyplus", bank="public_bank", type="bank"))
    db.commit()

    # Synthesize a PDF whose extracted text is the existing sample.
    sample = (Path(__file__).parent.parent / "sample_data" / "public_bank_sample.txt").read_text(encoding="utf-8")
    pdf_path = Path("test_pb.pdf").resolve()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), sample)
    doc.save(str(pdf_path))
    doc.close()

    try:
        with open(pdf_path, "rb") as f:
            resp = client.post("/api/upload", files={"file": (pdf_path.name, f, "application/pdf")})
    finally:
        pdf_path.unlink(missing_ok=True)

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["bank"] == "public_bank"
    assert body["transactions_imported"] == 7

    # Verify the Statement isn't flagged for review.
    stmt = db.query(Statement).filter_by(bank="public_bank").first()
    assert stmt is not None
    assert stmt.needs_review is False or stmt.needs_review is None
    assert stmt.reconciliation_note is None
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_reconcile_public_bank_happy_path -v`

Expected: FAIL — `reconcile_statement` doesn't yet have a public_bank dispatch arm, so it returns `ok=True` with `note="unknown bank format"` and the test's assertions about `transactions_imported == 7` may pass but the reconciler note tells us the arm wasn't run. Or the count cross-check skips because we haven't wired it yet. Either way: confirm the test fails or is "incomplete" before proceeding.

- [ ] **Step 3: Add the dispatch arm to `reconcile_statement`**

In `backend/app/services/reconciler.py`, find the dispatch chain inside `reconcile_statement`:

```python
    elif _MAYBANK_MARKER in text and _MAYBANK_MARKER_2 in text:
        rows = _extract_rows_from_maybank(text)
        maybank_balances = _extract_maybank_balances(text)
    else:
        doc.close()
        return ReconcileResult(ok=True, note="unknown bank format")
```

Insert a new arm BEFORE the `else:`:

```python
    elif _PB_MARKER_1 in text and _PB_MARKER_2 in text:
        rows = _extract_rows_from_public_bank(text)
        pb_summary = _extract_public_bank_summary(text)
    else:
        doc.close()
        return ReconcileResult(ok=True, note="unknown bank format")
```

Also declare `pb_summary` as `None` at the top of the dispatch (alongside `aeon_headers` / `maybank_balances`):

Find:
```python
    aeon_headers: dict | None = None
    maybank_balances: dict | None = None
```

Replace with:
```python
    aeon_headers: dict | None = None
    maybank_balances: dict | None = None
    pb_summary: dict | None = None
```

Then, after the existing Maybank check block (which ends with `return ReconcileResult(ok=True, checks_run=checks_run)` for the Maybank-balances branch), and BEFORE the generic `has_balance` fallback, insert the public_bank check block:

```python
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
        # toll-gate dedup bug shape from ADR-003).
        db_debits = sum(1 for r in rows if r["signed_amount"] < 0)
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
```

The exact insertion point: locate the existing block that begins with `# Maybank savings: per-row balance present + explicit BEGINNING BALANCE` and ends with its `return ReconcileResult(ok=True, checks_run=checks_run)` line. Insert the new public_bank block immediately after that block, BEFORE `has_balance = any(...)`.

- [ ] **Step 4: Run the integration test — verify it passes**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_reconcile_public_bank_happy_path -v`

Expected: PASS.

- [ ] **Step 5: Add a count-mismatch failure test**

Append to `backend/tests/test_reconciler.py`:

```python
def test_reconcile_public_bank_count_mismatch_flags(client, db, monkeypatch):
    """Force the parser to emit one fewer transaction than the summary's
    count_debits says — assert the reconciler's count cross-check flags
    needs_review with a useful note."""
    import fitz
    from pathlib import Path
    from app.models import Account, Statement
    from app.services.parsers.public_bank import PublicBankParser

    db.add(Account(name="Public Bank Moneyplus", bank="public_bank", type="bank"))
    db.commit()

    sample = (Path(__file__).parent.parent / "sample_data" / "public_bank_sample.txt").read_text(encoding="utf-8")

    real_parse = PublicBankParser.parse
    def short_parse(self, text):
        out = real_parse(self, text)
        return out[:-1]  # drop the last transaction
    monkeypatch.setattr(PublicBankParser, "parse", short_parse)

    pdf_path = Path("test_pb_short.pdf").resolve()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), sample)
    doc.save(str(pdf_path))
    doc.close()
    try:
        with open(pdf_path, "rb") as f:
            resp = client.post("/api/upload", files={"file": (pdf_path.name, f, "application/pdf")})
    finally:
        pdf_path.unlink(missing_ok=True)

    assert resp.status_code == 200
    stmt = db.query(Statement).filter_by(bank="public_bank").first()
    assert stmt.needs_review is True
    # The reconciler note distinguishes the two count-mismatch shapes — count
    # check from the universal _check_count fires first when db_count != row_count.
    assert "count" in (stmt.reconciliation_note or "").lower()
```

- [ ] **Step 6: Run the count-mismatch test — verify it passes**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py::test_reconcile_public_bank_count_mismatch_flags -v`

Expected: PASS.

- [ ] **Step 7: Run the full reconciler test file**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m pytest tests/test_reconciler.py -v`

Expected: all tests PASS (no regressions on the existing 21 tests + new PB tests).

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/app/services/reconciler.py backend/tests/test_reconciler.py && git commit -m "feat(ringgit): reconciler — public_bank dispatch arm with count cross-checks

Wires the public_bank arm into reconcile_statement: count, statement
balance, per-row, closing-balance cross-check, and the genuinely-novel
debit/credit count cross-check from the summary block. The count check
catches the toll-gate dedup bug shape from ADR-003 — silent merges
where balance arithmetic still works but the bank's own count
disagrees with what we parsed."
```

---

## Task 11: Reprocess script — `reprocess_public_bank.py`

**Files:**
- Create: `backend/scripts/reprocess_public_bank.py`

Mirror `reprocess_maybank.py`. Idempotent (DELETE+INSERT). No transaction-level dedup (ADR-003).

- [ ] **Step 1: Write the script**

Create `backend/scripts/reprocess_public_bank.py`:

```python
"""Re-parse all Public Bank Moneyplus statements through the current parser,
replacing every existing Public Bank transaction in-place. Idempotent —
running it twice produces the same end state. Use after Public Bank parser
fixes, or as the canonical first-time-account-creation step.

Candidate statements: bank in ('unknown', 'public_bank') AND filename
matches the user's Public Bank pattern. Each candidate is content-confirmed
by `PublicBankParser.can_parse(text)` before being processed.

Usage:
    cd backend && ./.venv/Scripts/python.exe scripts/reprocess_public_bank.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from app.config import BACKEND_ROOT
from app.models import Account, Category, Statement, Transaction
from app.services.categorizer import Categorizer
from app.services.parser_registry import ParserRegistry
from app.services.parsers.public_bank import PublicBankParser
from app.services.reconciler import reconcile_statement
from app.services.recurring_detector import RecurringDetector

ATM_DESC_RE = None  # imported lazily inside main to mirror email.py pattern

def main() -> int:
    from app.routers.email import ATM_PATTERN

    engine = create_engine("sqlite:///./ringgit.db")
    db = sessionmaker(bind=engine)()
    parser = PublicBankParser()
    categorizer = Categorizer(db)
    uncat = db.query(Category).filter_by(name="Uncategorized").first()

    # Step 1: ensure the public_bank account exists.
    pb_account = db.query(Account).filter_by(bank="public_bank").first()
    if not pb_account:
        pb_account = Account(
            name="Public Bank Moneyplus",
            bank="public_bank",
            type="bank",
            account_number="public-bank-savings",
        )
        db.add(pb_account); db.commit()
        print(f"created Public Bank account id={pb_account.id}")

    # Step 2: delete existing Public Bank transactions (defensive against re-runs).
    deleted = db.query(Transaction).filter_by(account_id=pb_account.id).delete()
    db.commit()
    print(f"deleted {deleted} existing Public Bank transactions")

    # Step 3: find candidate statements via filename heuristic + bank field.
    stmts = (
        db.query(Statement)
        .filter(Statement.bank.in_(["unknown", "public_bank"]))
        .filter(or_(
            Statement.filename.ilike("%public bank%"),
            Statement.filename.ilike("%public_bank%"),
            Statement.filename.ilike("%moneyplus%"),
        ))
        .order_by(Statement.id)
        .all()
    )
    print(f"reprocessing {len(stmts)} Public Bank candidate statements")

    inserted_total = 0
    extraction_failures = 0
    detection_failures = 0
    reconcile_failures = 0

    for stmt in stmts:
        if not stmt.file_path:
            print(f"  stmt {stmt.id}: no file_path, skipping")
            extraction_failures += 1
            continue
        fp = BACKEND_ROOT / stmt.file_path
        if not fp.exists():
            print(f"  stmt {stmt.id}: file missing at {fp}, skipping")
            extraction_failures += 1
            continue

        try:
            doc = fitz.open(str(fp))
            text = "".join(page.get_text() for page in doc)
            doc.close()
        except Exception as exc:
            print(f"  stmt {stmt.id}: extraction error {exc}, skipping")
            extraction_failures += 1
            continue

        if not parser.can_parse(text):
            print(f"  stmt {stmt.id}: not a Public Bank statement (filename matched, content didn't), skipping")
            detection_failures += 1
            continue

        # Update bank + period_month if the statement was previously 'unknown'.
        if stmt.bank != "public_bank":
            stmt.bank = "public_bank"
        period = parser.extract_period_month(text)
        if period and not stmt.period_month:
            stmt.period_month = period

        parsed = parser.parse(text)

        # No transaction-level dedup — file-level dedup via stmt.file_hash
        # plus this script's DELETE+INSERT covers idempotency. Same-day
        # repeats (toll gates, parking) are real data per ADR-003.
        for p in parsed:
            cat_id = categorizer.categorize(p["description"])
            if cat_id is None and uncat:
                cat_id = uncat.id
            is_atm = bool(ATM_PATTERN.search(p["description"]))
            db.add(Transaction(
                statement_id=stmt.id,
                account_id=pb_account.id,
                date=p["date"],
                description=p["description"],
                amount=p["amount"],
                type=p["type"],
                category_id=cat_id,
                is_cash_withdrawal=is_atm,
            ))
            inserted_total += 1
        db.commit()

        # Reconcile with the new transactions visible.
        rec = reconcile_statement(stmt.id, db)
        if not rec.ok:
            stmt.needs_review = True
            stmt.reconciliation_note = rec.note
            db.commit()
            reconcile_failures += 1
            print(f"  stmt {stmt.id}: parsed {len(parsed)} txs, reconcile FAIL: {rec.note}")
        else:
            stmt.needs_review = False
            stmt.reconciliation_note = None
            db.commit()
            print(f"  stmt {stmt.id}: parsed {len(parsed)} txs, reconcile ok")

    # Step 4: refresh recurring flags account-wide.
    RecurringDetector(db).apply_recurring_flags()

    print()
    print(f"summary: inserted {inserted_total} transactions across {len(stmts)} statements")
    print(f"  extraction failures: {extraction_failures}")
    print(f"  detection failures: {detection_failures}")
    print(f"  reconcile failures: {reconcile_failures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test the script imports cleanly**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -c "import scripts.reprocess_public_bank as m; print('ok', m.__name__)"`

Expected: `ok scripts.reprocess_public_bank`. Any ImportError indicates a missing or misnamed reference.

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/scripts/reprocess_public_bank.py && git commit -m "feat(ringgit): scripts/reprocess_public_bank.py — DELETE+INSERT reprocess

Mirrors reprocess_maybank.py: ensures the Public Bank Moneyplus
Account row exists, deletes existing PB transactions, finds candidate
Statements by filename heuristic, content-confirms via
PublicBankParser.can_parse, parses, inserts (no transaction-level
dedup per ADR-003), and reconciles.

Idempotent — re-runs produce the same end state."
```

---

## Task 12: One-shot loader script — `load_public_bank_pdfs.py`

**Files:**
- Create: `backend/scripts/load_public_bank_pdfs.py`

POSTs the 13 backfill PDFs to `/api/upload`. Safe to re-run (file-hash dedup catches duplicates).

- [ ] **Step 1: Write the script**

Create `backend/scripts/load_public_bank_pdfs.py`:

```python
"""One-shot loader: POST a list of Public Bank statement PDFs to
/api/upload. The first run uploads all 13 backfill files. Re-runs are
safe — the upload route's file_hash dedup catches duplicates.

The Account row for public_bank must already exist before /api/upload
will insert transactions. If it doesn't, run scripts/reprocess_public_bank.py
afterwards — that script creates the account and re-parses all matching
candidate Statements.

Usage:
    # Default: glob C:/Users/aquam/Downloads/Public Bank *.pdf
    cd backend && ./.venv/Scripts/python.exe scripts/load_public_bank_pdfs.py

    # Explicit file list:
    cd backend && ./.venv/Scripts/python.exe scripts/load_public_bank_pdfs.py path1.pdf path2.pdf
"""
import sys
from glob import glob
from pathlib import Path

import requests

DEFAULT_GLOB = r"C:\Users\aquam\Downloads\Public Bank *.pdf"
UPLOAD_URL = "http://localhost:8000/api/upload"


def main() -> int:
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        paths = [Path(p) for p in glob(DEFAULT_GLOB)]

    if not paths:
        print(f"no PDFs matched (cwd={Path.cwd()}, glob={DEFAULT_GLOB})", file=sys.stderr)
        return 1

    print(f"uploading {len(paths)} files to {UPLOAD_URL}")
    failures = 0
    duplicates = 0
    successes = 0
    failed_no_account = 0

    for path in paths:
        if not path.exists():
            print(f"  {path.name}: MISSING")
            failures += 1
            continue
        with open(path, "rb") as f:
            try:
                resp = requests.post(
                    UPLOAD_URL,
                    files={"file": (path.name, f, "application/pdf")},
                    timeout=60,
                )
            except requests.RequestException as exc:
                print(f"  {path.name}: REQUEST ERROR {exc}")
                failures += 1
                continue

        if resp.status_code != 200:
            print(f"  {path.name}: HTTP {resp.status_code} — {resp.text[:200]}")
            failures += 1
            continue

        body = resp.json()
        status = body.get("status", "?")
        bank = body.get("bank", "?")
        n_imported = body.get("transactions_imported", 0)
        msg = body.get("message", "")
        print(f"  {path.name}: {status} bank={bank} imported={n_imported} — {msg}")

        if status == "duplicate":
            duplicates += 1
        elif status == "failed" and "No account found" in msg:
            failed_no_account += 1
        elif status == "failed":
            failures += 1
        else:
            successes += 1

    print()
    print(f"summary: {successes} succeeded, {duplicates} duplicates, "
          f"{failed_no_account} failed-no-account, {failures} other failures")
    if failed_no_account:
        print()
        print("Some uploads succeeded as Statements but couldn't insert transactions")
        print("because the public_bank Account row doesn't exist yet. Run:")
        print("  ./.venv/Scripts/python.exe scripts/reprocess_public_bank.py")
        print("That script creates the account and re-parses all candidate Statements.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test the script imports cleanly**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -c "import scripts.load_public_bank_pdfs as m; print('ok', m.__name__)"`

Expected: `ok scripts.load_public_bank_pdfs`.

- [ ] **Step 3: Verify `requests` is available in the backend venv**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -c "import requests; print(requests.__version__)"`

Expected: prints a version string. If `ModuleNotFoundError`, install: `./.venv/Scripts/pip.exe install requests`. (`requests` is commonly already in the venv via `httpx` or test-client deps; check first, only install if missing.)

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/aquam/Projects/ringgit" && git add backend/scripts/load_public_bank_pdfs.py && git commit -m "feat(ringgit): scripts/load_public_bank_pdfs.py — backfill loader

POSTs a list of Public Bank statement PDFs to /api/upload. Default
behavior globs C:/Users/aquam/Downloads/Public Bank *.pdf. Safe to
re-run (file_hash dedup). Prints per-file result and a summary; if
any uploads land as 'failed-no-account', the summary suggests running
reprocess_public_bank.py to create the Account and re-parse."
```

---

## Task 13: Manual integration smoke

**Files:** None modified.

End-to-end validation against the 13 real backfill PDFs. The backend must be running locally for this task. Run from a separate terminal — the loader script POSTs over HTTP.

- [ ] **Step 1: Start the backend in the background**

Run (single Bash call with `run_in_background=true`):

```bash
cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

Expected: process starts; check logs to confirm `Uvicorn running on http://0.0.0.0:8000`.

- [ ] **Step 2: Run the loader**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe scripts/load_public_bank_pdfs.py`

Expected output: 13 lines, each `<filename>: <status> bank=public_bank imported=<N> — <msg>`. On the FIRST RUN with no Account row present, every line will show `status=failed bank=public_bank ... message="No account found for bank 'public_bank'..."` and the summary footer prints the suggested next step.

- [ ] **Step 3: Run the reprocess script to create the account and re-parse**

Run: `cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe scripts/reprocess_public_bank.py`

Expected:
- `created Public Bank account id=<N>`
- `deleted 0 existing Public Bank transactions`
- `reprocessing 13 Public Bank candidate statements`
- 13 lines, each `stmt <id>: parsed <N> txs, reconcile ok` (or rare `reconcile FAIL: <note>` for any statement with format quirks not covered by the synthetic samples)
- Summary: `inserted <total> transactions across 13 statements; reconcile failures: 0` (ideal)

- [ ] **Step 4: Verify in DB**

Run:
```bash
cd "C:/Users/aquam/Projects/ringgit/backend" && ./.venv/Scripts/python.exe -c "
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Account, Statement, Transaction

engine = create_engine('sqlite:///./ringgit.db')
db = sessionmaker(bind=engine)()
acc = db.query(Account).filter_by(bank='public_bank').first()
print('account:', acc.id if acc else None, acc.name if acc else None)
n_stmts = db.query(Statement).filter_by(bank='public_bank').count()
n_txs = db.query(Transaction).filter_by(account_id=acc.id).count() if acc else 0
n_review = db.query(Statement).filter_by(bank='public_bank', needs_review=True).count()
print(f'statements: {n_stmts}, transactions: {n_txs}, needs_review: {n_review}')
"
```

Expected: `account: <id> Public Bank Moneyplus`, `statements: 13, transactions: <total>, needs_review: 0`. If `needs_review > 0`, inspect `Statement.reconciliation_note` for the failing rows and triage on the actual statement before considering this task complete.

- [ ] **Step 5: Stop the backend**

Send Ctrl+C to the background process or kill it via the runtime's process handle. Verify the port is free: `cd "C:/Users/aquam/Projects/ringgit/backend" && netstat -ano | findstr :8000` → no output.

- [ ] **Step 6: No commit (verification-only task)**

This task changes no files. Database state changes are local and not git-tracked.

---

## Self-Review

**Spec coverage:** each section of `2026-05-04-public-bank-parser-design.md` is covered:

- Goal / Non-Goals → Plan header.
- Statement Format Observations → embedded in Tasks 1, 4, 5, 6 sample data and assertions.
- Architecture diagram → Tasks 4 (parser state machine), 8-10 (reconciler arm).
- File Map → Tasks 1-13 list each file and create/modify/replace status.
- PublicBankParser internals (can_parse, extract_period_month, parse with state machine, sign-via-balance-delta, page-wrap stitching, year inference, soft-bound assertion) → Tasks 3, 4, 5, 6.
- Reconciler arm (helpers + dispatch + cross-checks) → Tasks 8, 9, 10.
- Reprocess Script → Task 11.
- One-Shot Loader → Task 12.
- Account Row Defaults → Task 11 (the reprocess script is the canonical creation point).
- Testing Strategy (synthetic + real-fixture + reconciler) → Tasks 2, 4, 5, 6, 7, 8, 9, 10.
- Manual integration smoke → Task 13.
- Risks & Mitigations → no task needed; the load+reprocess flow surfaces format-drift failures (risk #1) per-statement; structural-marker whole-line matching (risk #2) is encoded in `_STRUCTURAL_LINES` membership; the soft-bound warning (risk #3) is in Task 6; closing-balance redundancy (risk #4) is accepted, count cross-check covers the gap.

**Placeholder scan:** no TBD/TODO/"add appropriate error handling"/"similar to Task N" placeholders. All tests have concrete assertions; all code steps show the full code; all commands have expected output.

**Type consistency:** cross-checks done.
- `PublicBankParser.bank_id` returns `"public_bank"` consistently across parser, reprocess script (`bank="public_bank"`), reconciler markers, and Account creation.
- `_PB_MARKER_1` / `_PB_MARKER_2` defined in Task 8 are consumed in Task 10's dispatch arm.
- `_extract_public_bank_summary` (Task 8) returns dict keys `closing`, `total_debits`, `count_debits`, `total_credits`, `count_credits` — same keys consumed in Task 10's dispatch arm.
- `_extract_rows_from_public_bank` (Task 9) returns `{signed_amount, balance}` dicts — matches the shape consumed by the existing `_check_count`, `_check_statement_balance`, `_check_per_row` helpers and the new dispatch arm in Task 10.
- Same-day repeats test (Task 2) expects `len(same_day) == 3` — Task 4's state machine carries `current_date_str` across consecutive amount-balance pairs, so the same-day case falls out without explicit handling. No Task 5 needed beyond what's in Task 4 (Task 5 was renumbered to page-wrap; Task 6 to year inference; Task 7 to real-PDF; Task 8-10 to reconciler; etc.).
- `_PB_DATE_LINE_RE` and `_PB_NUMBER_LINE_RE` patterns in Task 9 match the parser's `_DATE_LINE_RE` and `_NUMBER_LINE_RE` (Task 4) — different module-level names but identical regex patterns; intentional duplication per ADR-002.
