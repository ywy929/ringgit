# Public Bank Parser & Reconciliation — Design

**Status:** approved 2026-05-04
**Author:** Yeow + Claude
**Predecessors:** ADR-001 (anchor-based parsing), ADR-002 (reconciliation as runtime guardrail), ADR-003 (file-level dedup only), ADR-004 (encrypted-stub fallback)

## Goal

Add a parser for **Public Bank Moneyplus Savings Account** PDF statements, plus a reconciler arm and a one-shot loader for backfilling 13 statements (Apr 2025 → Apr 2026) the user has downloaded manually. Replaces the existing column-position scaffold at `backend/app/services/parsers/public_bank.py` with an anchor-based parser consistent with the Maybank/AEON precedents.

## Non-Goals

- Gmail-fetch wiring (PB statements are not received by email; manual-download only).
- Password handling (PB PDFs are not encrypted).
- Maybank reconciler enhancements (asymmetry between PB and Maybank is justified by what each bank's statement exposes; counts only appear in PB summary).
- Frontend UI changes — parser is invisible to the UI.
- Categorizer keyword tuning — the existing learning categorizer handles new descriptions through user corrections.

## Statement Format Observations (from 4 sampled PDFs)

All Public Bank Moneyplus Savings statements share:

- **Bilingual** BM/EN labels paired throughout.
- **Statement date** format `DD MMM YYYY` (e.g., `03 Apr 2026`) appearing after `Tarikh Penyata / Statement Date`.
- **Account number** `5099012333` after `Nombor Akaun / Account Number`.
- **Account type** line `Jenis Akaun / Account Type RM Moneyplus Savings Account`.
- **Summary block** appearing after the column header, in fixed 5-line order:
  ```
  <closing-balance>      e.g. 8,921.73
  <total-debits>         e.g. 11,651.60
  <count-debits>         e.g. 9
  <total-credits>        e.g. 1,503.64
  <count-credits>        e.g. 2
  ```
- **Transaction-section start** marked by `Balance From Last Statement` (carries the opening balance value).
- **Transaction-section end** marked by `Closing Balance In This Statement`.
- **Transaction date** format `DD/MM` (no year on the line itself; year is inferred from statement date).
- **Per-transaction lines** (PyMuPDF text extraction collapses the debit/credit columns):
  ```
  DD/MM            <- date, omitted on same-day repeats
  <amount>         <- single number, sign indeterminate from text alone
  <balance>        <- running balance (always present)
  <description>    <- 0..N text lines until next D/N/structural marker
  ```
- **Page breaks** introduce `Balance C/F → <balance>` (page 1 end) and `Balance B/F → <balance>` (page 2+ start). The previous transaction's description can wrap across this boundary, appearing as orphan text lines after `Balance B/F → <balance>` and before the next date.
- **Amounts** are plain `[\d,]+\.\d{2}` — no `RM` prefix.

## Architecture

```
PDF bytes ──▶ PyMuPDF text extraction ──▶ PublicBankParser.parse
                                          ├─ can_parse: 2-marker text check
                                          ├─ extract_period_month: statement-date regex
                                          └─ parse: state machine over [Balance From Last Statement,
                                                    Closing Balance In This Statement] section,
                                                    sign via balance delta, page-wrap stitching

Statement insert ──▶ reconcile_statement (existing dispatch)
                     └─ public_bank arm:
                        ├─ _extract_rows_from_public_bank   (mirrors parse, emits {signed, balance})
                        ├─ _extract_public_bank_summary     (5-line summary regex)
                        └─ checks: count, statement_balance, per_row,
                                   closing-balance cross-check, count cross-check
```

## File Map

### New
- `backend/app/services/parsers/public_bank.py` — full rewrite (replaces column-position scaffold)
- `backend/scripts/reprocess_public_bank.py` — DELETE+INSERT reprocess (mirrors `reprocess_maybank.py`)
- `backend/scripts/load_public_bank_pdfs.py` — one-shot loader, POSTs the 13 backfill files to `/api/upload`
- `backend/tests/parsers/test_public_bank.py` — synthetic + real-fixture parser tests
- `backend/tests/test_reconciler_public_bank.py` — reconciler arm tests
- `backend/tests/fixtures/public_bank/{apr_2025,apr_2026,jan_2026}.pdf` — staged real fixtures (skipif-gated like the existing Maybank/AEON real-fixture tests)

### Modified
- `backend/app/services/reconciler.py` — add `_extract_rows_from_public_bank`, `_extract_public_bank_summary`, marker constants, dispatch arm in `reconcile_statement`

### Untouched
- `parser_registry.py` — Public Bank is already registered in the parser list
- `email.py` — no Gmail wiring this round
- `config.py` — no password env var (PB PDFs are not encrypted)
- Maybank reconciler arm — asymmetry deliberately preserved

## `PublicBankParser` Internals

### `can_parse(text) -> bool`

Two-marker strict check:

```python
return "Public Bank" in text and "Moneyplus Savings Account" in text
```

The bilingual generic `PENYATA AKAUN / STATEMENT OF ACCOUNT` is intentionally not used — Maybank/AEON would also match it. The two markers above appear in every sampled PB statement and would not appear together in any other shipped bank.

### `extract_period_month(text) -> str`

Match the bilingual block:
```
Tarikh Penyata / Statement Date
03 Apr 2026
```

Regex: `Tarikh Penyata / Statement Date\s*\n\s*(\d{2}\s+\w{3}\s+\d{4})`. Parse with `datetime.strptime(m.group(1), "%d %b %Y")`. Return `dt.strftime("%Y-%m")`. Return `""` on miss or `ValueError`.

### `parse(text) -> list[ParsedTransaction]`

State machine over text lines. Bounded by:
- **Section start:** first occurrence of the standalone line `Balance From Last Statement`. Walk back one line for the date, walk forward one line for the opening balance value (used to seed `prev_balance`).
- **Section end:** first occurrence of the standalone line `Closing Balance In This Statement`.

Within the section, classify each line:

| Classifier | Pattern |
|------------|---------|
| `D` (date) | `^\d{2}/\d{2}$` |
| `N` (number) | `^[\d,]+\.\d{2}$` |
| `S` (structural) | line ∈ `{"Balance From Last Statement", "Balance B/F", "Balance C/F"}` OR matches column-header tokens (`TARIKH`, `URUS NIAGA`, `DEBIT`, `KREDIT`, `BAKI`, `DATE`, `TRANSACTION`, `CREDIT`, `BALANCE`) OR matches page footer (`Muka Surat \d+ Daripada \d+`, `Page \d+ of \d+`) OR matches the bilingual disclaimer / branch / privacy / address noise that appears mid-text on page 2+ |
| `T` (text) | otherwise |

#### Per-transaction extraction

The state machine maintains:
- `current_date` — most recent `D` line seen (carries down for same-day repeats)
- `current_year` — derived per `current_date` via year-inference rule below
- `prev_balance` — running balance carried from the previous transaction (or opening balance from `Balance From Last Statement`)
- `last_tx` — the most recently emitted `ParsedTransaction`, used for page-wrap description appending

A transaction is the line pattern:

```
[D?] N N T*
```

When two consecutive `N` lines are detected, treat the first as `amount` and the second as `curr_balance`. Compute `signed = curr_balance - prev_balance`; if `signed >= 0` then `type="credit"` and `amount = signed`, else `type="debit"` and `amount = -signed`. Then collect subsequent `T` lines as the description until a non-`T` line. Update `prev_balance = curr_balance`.

#### Page-wrap stitching

The page-break sequence is:

```
Balance C/F      <- structural
<balance>        <- N
[page-header noise classified as S]
[D?]             <- date may or may not repeat on page 2
Balance B/F      <- structural
<balance>        <- N (matches the C/F balance)
<orphan-T-lines> <- description fragments belonging to the previous transaction
[next D]
```

When the state machine encounters this sequence, it consumes the structural `Balance C/F → N` and `Balance B/F → N` pairs, skips intermediate `S` lines, and any `T` lines appearing **after** `Balance B/F → N` and **before** the next `D` or `N` are appended (with single-space separator) to `last_tx.description`. The `D` line that may repeat between `Balance C/F` and `Balance B/F` is consumed but does not produce a transaction (it's just the date column repeating to anchor the carry-forward row).

#### Year inference

Statement date provides `(M_s, Y_s)`. For each `DD/MM` transaction date:
- if `MM > M_s` → year is `Y_s - 1`
- else → year is `Y_s`

This works for all 13 sampled statements (e.g., Jan 2026 statement contains `03/12, 31/12` → Dec 2025; Apr 2026 statement contains `03/03 … 02/04` → 2026).

**Soft-bound assertion:** for every emitted transaction, verify the inferred date is within `[stmt_date - 40 days, stmt_date]`. If not, leave the transaction in the output but log a warning (no exception). This is a runtime-tripwire only; the reconciler is the authoritative guardrail.

#### `Balance From Last Statement` row

Pattern:
```
DD/MM
Balance From Last Statement
<opening-balance>
```

Detected when `last_seen_S == "Balance From Last Statement"` is between a `D` and an `N`. Sets `prev_balance = opening_balance`. Emits no transaction.

## Reconciler Arm

### New helpers in `reconciler.py`

```python
_PB_MARKER_1 = "Moneyplus Savings Account"
_PB_MARKER_2 = "Closing Balance In This Statement"

_PB_SUMMARY_RE = re.compile(
    r"BALANCE\s*\n"                       # column header end
    r"([\d,]+\.\d{2})\s*\n"               # closing
    r"([\d,]+\.\d{2})\s*\n"               # total debits
    r"(\d+)\s*\n"                         # count debits
    r"([\d,]+\.\d{2})\s*\n"               # total credits
    r"(\d+)\s*\n",                        # count credits
    re.MULTILINE,
)

def _extract_public_bank_summary(text: str) -> dict | None:
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

def _extract_rows_from_public_bank(text: str) -> list[dict]:
    # Mirrors PublicBankParser.parse — same section bounds (Balance From Last
    # Statement → Closing Balance In This Statement), same line classifier,
    # same state machine, same balance-delta sign rule, same page-wrap
    # consumption — but emits {signed_amount, balance} dicts instead of
    # ParsedTransaction. Description stitching is omitted (the reconciler
    # doesn't care about descriptions). Body is a near-duplicate of parse()
    # by design: ADR-002 keeps the reconciler independent of the parser, so
    # the duplicated state-machine logic is the cost of that independence.
    ...
```

The `_extract_rows_from_public_bank` mirrors the parser's state machine. Both functions share the same line-classification logic but are deliberately not extracted into a shared helper module — keeping them per-file means a regression in one isn't masked by a regression in the other (ADR-002 calls this out as a cost of the reconciler-as-independent-guardrail design).

### Dispatch in `reconcile_statement`

Insert before the existing fallback:

```python
elif _PB_MARKER_1 in text and _PB_MARKER_2 in text:
    rows = _extract_rows_from_public_bank(text)
    pb_summary = _extract_public_bank_summary(text)
```

Then after the universal count check:

```python
if pb_summary is not None and rows:
    checks_run.append("statement")
    r = _check_statement_balance(rows)
    if not r.ok:
        return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

    checks_run.append("per_row")
    r = _check_per_row(rows)
    if not r.ok:
        return ReconcileResult(ok=False, note=r.note, checks_run=checks_run)

    # Closing-balance cross-check (catches truncation that lands on a clean number).
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

    # Count cross-check (genuinely novel — catches silent merges/drops where
    # balance arithmetic still happens to work, e.g., the toll-gate dedup
    # bug shape from ADR-003).
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

If `pb_summary is None`, fall through to the existing generic `has_balance` block — runs count + statement-balance + per-row only, with `note="summary block not found"`. Under-flag rather than cry wolf, matching ADR-002.

## Reprocess Script (`reprocess_public_bank.py`)

Mirror of `reprocess_maybank.py`:

1. Open `ringgit.db`. Create `Public Bank Moneyplus` Account row if missing:
   - `name="Public Bank Moneyplus"`, `bank="public_bank"`, `type="bank"`, `account_number="public-bank-savings"` (slug, matches Maybank precedent rather than embedding the real account number).
2. `DELETE FROM transaction WHERE account_id = <pb_account_id>` for idempotency.
3. Find candidate statements via filename heuristic: `bank IN ('unknown', 'public_bank')` AND `(filename LIKE '%public_bank%' OR filename LIKE '%Public Bank%' OR filename LIKE '%moneyplus%')`.
4. For each candidate:
   - Open the PDF (no password — PB PDFs are not encrypted).
   - Content-confirm via `PublicBankParser().can_parse(text)`. Skip if `False` (defensive against false-positive filename match).
   - `parser.parse(text)` → list of `ParsedTransaction`.
   - **No transaction-level dedup** (ADR-003): the bank's statement is the source of truth and same-day same-amount repeats are real data.
   - Insert each transaction with `account_id = <pb_account_id>`, `statement_id = stmt.id`. Categorize via `Categorizer`. Set `is_cash_withdrawal` from the existing `ATM_PATTERN` regex.
   - Update `stmt.bank = "public_bank"` and `stmt.period_month = parser.extract_period_month(text)` if currently empty/unknown.
5. After insert, call `reconcile_statement(stmt.id, db)` and set `needs_review` + `reconciliation_note` if it fails.
6. Print per-statement progress + summary counts (created / skipped / failed / inserted).

## One-Shot Loader (`load_public_bank_pdfs.py`)

Backfill helper for the 13 PDFs the user has in `Downloads/`:

1. Read PDF paths from `sys.argv[1:]`. If empty, glob `C:\Users\aquam\Downloads\Public Bank *.pdf`.
2. For each path: POST as multipart form-data to `http://localhost:8000/api/upload` with field name `file` (matches `upload.py`'s `file: UploadFile = File(...)` param). Omit the `password` form field — PB PDFs are not encrypted.
3. Print per-file result (status / bank / transactions imported / message).
4. After all files are uploaded, print suggested follow-up: `python scripts/reprocess_public_bank.py` (only needed for future parser fixes — first-time upload runs the parser inline via the upload route).

The loader is safe to re-run: file-hash dedup catches re-uploads as `status="duplicate"`.

## Account Row Defaults

If `reprocess_public_bank.py` (or the upload path's account-lookup) finds no `public_bank` Account, it creates one with:

| field | value |
|-------|-------|
| `name` | `Public Bank Moneyplus` |
| `bank` | `public_bank` |
| `type` | `bank` |
| `account_number` | `public-bank-savings` (slug; matches Maybank precedent of not embedding the real number) |

## Testing Strategy

### Synthetic-fixture unit tests (`tests/parsers/test_public_bank.py`)

Always run; embedded sample text in test source.

- `test_can_parse_positive` — text with both markers → `True`
- `test_can_parse_negative_maybank` — Maybank text (has "Malayan Banking Berhad", lacks PB markers) → `False`
- `test_can_parse_partial_marker` — text with `"Public Bank"` but not `"Moneyplus Savings Account"` → `False`
- `test_extract_period_month` — `03 Apr 2026` → `2026-04`; missing date → `""`
- `test_parse_simple_credit` — single credit transaction; balance delta positive
- `test_parse_simple_debit` — single debit transaction; balance delta negative
- `test_parse_same_day_multiple` — three RM2.10 toll-gate-shape transactions on one date, all preserved (validates ADR-003 stance)
- `test_parse_opening_balance_skipped` — `Balance From Last Statement` row produces zero transactions but seeds `prev_balance` so the next transaction's sign is correct
- `test_year_inference_wrap` — Jan-statement synthetic chunk with Dec dates → year is `statement_year - 1`
- `test_page_wrap_description_stitched` — synthetic two-page chunk with description split across `Balance C/F` / `Balance B/F`; assert post-page-break `T` lines are appended to the previous transaction's description (single space separator)

### Real-fixture parser tests (skipif-gated)

Stage 3 PDFs in `backend/tests/fixtures/public_bank/` (chosen for coverage):

- `apr_2025.pdf` — small, single-page; debits and credits mixed
- `apr_2026.pdf` — multi-page with description-wrap (validates page-wrap stitching)
- `jan_2026.pdf` — smallest sample (one transaction); validates the empty-page-2 case

For each fixture:

- Open with PyMuPDF, extract text, assert `can_parse(text) is True`
- `parser.parse(text)` returns a list whose length equals `count_debits + count_credits` from the summary block
- Sum of signed amounts = `closing - opening` (where opening is the value extracted from `Balance From Last Statement`)
- No exceptions during parse

### Reconciler tests (`tests/test_reconciler_public_bank.py`)

- Happy path on each of the 3 staged real fixtures: `reconcile_statement` returns `ok=True` and `checks_run` includes `"count"`, `"statement"`, `"per_row"`
- Synthetic count-mismatch: feed text where the parser would produce N rows but `summary.count_debits + count_credits = N+1`; assert the count cross-check fails with a useful note
- Synthetic summary-not-found: text with PB markers but the summary block stripped; assert checks 4 and 5 are skipped, generic `has_balance` block runs, result is `ok=True`

### Manual integration smoke (post-implementation, not in test suite)

- Start backend
- Run `python scripts/load_public_bank_pdfs.py`
- Expect 13 statements imported, all `needs_review = False`, no parser warnings about out-of-bound dates
- Expect Account `Public Bank Moneyplus` row exists with non-zero transactions

Documented as a step in the implementation plan; not automated.

## Risks & Mitigations

1. **Format drift on the 9 unsampled PDFs.** Sampled 4 of 13 (Apr 2025, Jan 2026, Mar 2026, Apr 2026). Other 9 may have shape variations not covered by sampled patterns. **Mitigation:** the load script's per-file result surfaces any reconciler failure; triage on the actual statement rather than guessing now.

2. **Page-wrap stitching false positives.** A description containing the literal substring `Balance B/F` could in principle confuse the stitcher. **Mitigation:** structural-marker detection matches whole standalone lines only, never substrings.

3. **Year inference at boundaries.** The current rule (MM > M_s → prior year) handles all sampled cases. If a future statement spans more than 1 month back, the rule could mis-infer. **Mitigation:** soft-bound assertion (date within `stmt_date ± 40 days`) logs a warning when violated; reconciler is the authoritative guardrail.

4. **Closing-balance cross-check is partially redundant.** The summary's closing balance and the footer `Closing Balance In This Statement` are the same value extracted twice; if both match a parser-truncated final balance, the check passes silently. **Acceptance:** the count cross-check (the actually-novel signal) covers the truncation case independently.

## References

- ADR-001 — Anchor-based parsing
- ADR-002 — Reconciliation as runtime guardrail
- ADR-003 — File-level dedup only
- ADR-004 — Encrypted-stub fallback (informational; PB doesn't trigger this path because PDFs aren't encrypted)
- Precedent specs:
  - `2026-05-02-maybank-savings-parser-design.md`
  - `2026-05-02-aeon-credit-card-parser-and-reconciliation-design.md`

## Revision History

| Date       | Author    | Changes                          |
|------------|-----------|----------------------------------|
| 2026-05-04 | Yeow      | Initial design                   |
