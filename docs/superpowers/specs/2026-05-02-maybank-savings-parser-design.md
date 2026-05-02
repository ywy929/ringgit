# Maybank Savings Account Parser + Reconciliation — Design

**Date:** 2026-05-02
**Status:** Approved (pending spec review before plan)
**Goal:** Add a working Maybank savings account parser (sender `m2u@stmts.maybank2u.com.my`) covering both the 2018 GST-era format and the 2026 post-GST format, plus reconciler dispatch using per-row + statement-level checks. Reprocess the 61 existing encrypted-stub statements through the new parser.

## Context

After landing TnG and AEON parsers, Maybank is the third bank with available data. The user's gmail inbox has **61 encrypted Maybank PDFs** going back to 2018, currently sitting as `bank='unknown'` stubs. They are decryptable with the password configured in `PDF_PASSWORD_MAYBANK` (verified working on all 61 PDFs).

A spike on real PDFs confirmed three things:

1. **The format has evolved across two eras.** Pre-September 2018 statements include a `JENIS GST / GST TYPE` column and an explicit `ENDING BALANCE / TOTAL CREDIT / TOTAL DEBIT` summary in the footer. Post-2018 statements drop the GST column (Malaysia abolished GST and replaced it with SST in September 2018) and drop the explicit ending-balance trio. Both eras share the same anchor structure (date lines, signed amounts, running balance per row), so a single anchor-based parser handles both by ignoring the extra GST line rather than depending on column positions.

2. **`Page.find_tables()` has not been validated for Maybank.** Following the AEON precedent, we use anchor-based text parsing directly. The trilingual headers (BM/Chinese/English) in column labels would likely confuse find_tables anyway. If a future need arises to switch, the parser can be revisited.

3. **Per-row running balance is present** (the `STATEMENT BALANCE / BAKI PENYATA / 結單存餘` column). This is the same affordance TnG legacy provides. Maybank's reconciler arm therefore does both per-row and statement-level checks — strictest possible coverage with no extra work, since the reconciler already has the building blocks.

The existing `MaybankParser` is fictional-sample-tuned column-position regex. Full rewrite expected.

## Architecture & Phase Sequencing

Two phases, sequenced so each validates against the next:

**Phase 1 — Parser + reconciler dispatch.** Rewrite `app/services/parsers/maybank.py` from scratch using anchor-based parsing. Extend `reconcile_statement` with a fourth format-detection arm for Maybank. The reconciler runs count check + per-row check + statement-level check (with explicit `ENDING BALANCE` cross-check when present in 2018-era statements).

**Phase 2 — Reprocess.** New `backend/scripts/reprocess_maybank.py` that finds the 61 statements, decrypts with `PDF_PASSWORD_MAYBANK`, parses with the new parser, dedups via broad key (no per-tx refs available), inserts. The existing `reconcile_existing.py` script re-runs at the end to backfill the `needs_review` flag.

**Dependency chain:** Phase 1 → Phase 2.

## Scope Exclusions

- **Maybank credit card / current account / fixed deposit parsers.** Out of scope. Only the savings statement format observed in the user's data is supported. If future Maybank products arrive, they get their own parser file (e.g., `maybank_cc.py`) and a separate `bank_id`.
- **`find_tables()`-based parsing for Maybank.** Not attempted. Anchor-based works and is easier to reason about.
- **OCR fallback.** Not needed — all 61 PDFs decrypt and yield clean text via PyMuPDF.
- **Refactoring shared anchor-based parser logic into a base class.** Premature. TnG, AEON, and Maybank each have format-specific quirks; today there's no common interface that doesn't leak abstraction.
- **Externalizing per-bank reconciler config.** Format dispatch stays hardcoded. We'll consider externalizing when there are 5+ banks; today there are 3.
- **Tax/GST as a separate field.** GST is metadata in old statements only; the transaction amount already includes any tax. We discard the GST column.

## Phase 1: Parser

### `app/services/parsers/maybank.py` — full rewrite

**`bank_id`:** `"maybank"` (savings account is the only Maybank product today; credit card etc. would get their own bank_id later if needed).

**`can_parse(text)`:** matches when text contains BOTH:
- `"Malayan Banking Berhad"` — definitive Maybank marker present in all observed statements (footer line)
- `"URUSNIAGA AKAUN"` — BM for "Account Transactions", part of the transaction-section header

The two-marker rule prevents collisions: just `"MAYBANK"` alone appears in unrelated text bleed (the way "Public Bank" appeared inside AEON statements). The combination is unique to a real Maybank statement.

**`extract_period_month(text)`:** matches the trilingual `STATEMENT DATE` block:

```
TARIKH PENYATA
結單日期
STATEMENT DATE
:
DD/MM/YY
```

Regex anchors on `"STATEMENT DATE"` then walks forward to find the next `^\d{2}/\d{2}/\d{2}$` line. Returns `"YYYY-MM"` after century inference.

**Century inference:** years `00–69` → `20YY`, years `70–99` → `19YY` (matches Python's `%y` strptime convention). All real Maybank data falls in `18–26`; the boundary is just a defensive sanity check.

**`parse(text)`:** anchor-based extraction.

**Anchor pattern:** a single line matching `^\d{2}/\d{2}/\d{2}$`. Each transaction is a chunk from one date anchor to the next.

**Transactions section bounds:**
- **Start:** the line `BEGINNING BALANCE` followed by an amount line. The amount on the next line is the opening balance (used by the reconciler, not as a transaction).
- **End:** the first of: `ENDING BALANCE :` (2018 era), `TERMS AND CONDITION APPLY` (footer), `Malayan Banking Berhad` (footer line), or end-of-text.

Pages 2+ repeat the column-header block. The parser skips any chunk where the type-label line is one of the known repeated header tokens (`TARIKH MASUK`, `BUTIR URUSNIAGA`, `JUMLAH URUSNIAGA`, `BAKI PENYATA`, `ENTRY DATE`, `TRANSACTION DESCRIPTION`, `TRANSACTION AMOUNT`, `STATEMENT BALANCE`, the Chinese equivalents, and `JENIS GST` / `GST TYPE` for old format).

**For each anchored chunk** (lines from one date anchor up to but not including the next):

| Field | Source |
|---|---|
| `date` | The date line itself, parsed `DD/MM/YY` → ISO `YYYY-MM-DD` with century inference |
| `type_label` | The next non-empty line after the date (e.g., `"TRANSFER FROM A/C"`, `"DEBIT ADVICE"`, `"FPX PAYMENT FR A/"`) |
| `signed_amount_line` | Walk forward from the type_label. The first line matching `^[\d,]+\.\d{2}[+-]$` is the signed amount line. |
| `balance_line` | The line immediately after the signed amount line, matching `^[\d,]+\.\d{2}$` (no sign suffix; this is the running balance) |
| `detail_lines` | Any remaining lines in the chunk after the balance line, with leading whitespace stripped. Includes lines like `"   SITTAL CARPARK SDN.*"`. |
| `description` | `f"{type_label} - {' '.join(detail_lines)}"` if detail_lines is non-empty, else `type_label` alone. Whitespace collapsed (multiple spaces → single space, trailing/leading stripped). |
| `amount` | The signed amount with the suffix stripped, parsed as Decimal (commas removed) |
| `transaction_type` | `"debit"` if signed amount ends with `-`, `"credit"` if ends with `+` |
| `external_reference` | `None` — Maybank doesn't expose per-transaction unique IDs |

**Walk-forward (not column-position):** identical robustness rationale as the TnG and AEON rewrites. PDF text extraction order is reliable line-by-line; column positions are not.

**GST line tolerance (old format):** the GST column line (e.g., `"SR"`) appears between the type label and the amount in old statements. It is **discarded**: it isn't part of `type_label` (only the first line after the date is captured), and it isn't part of `detail_lines` (those are after the balance line). The walk-forward to "first signed-amount line" passes over it with no special handling. Note that some old statements ALSO inline the GST tag in the type label itself (e.g., `"DEBIT ADVICE     SR"`); that variant is preserved as-is in the description, which is acceptable noise. This dual-shape tolerance is the key reason a single parser handles both eras.

Worked example, 2018-format chunk:
```
06/03/18         <- date anchor
DEBIT ADVICE  SR <- type_label (first line; inline SR tolerated)
SR               <- standalone GST line (discarded by walk-forward)
8.48-            <- signed_amount_line (first match of [\d,]+\.\d{2}[+-])
241.52           <- balance_line
   (INCLUSIVE OF GST RM     0.48)   <- detail_line (after balance)
```
Produces: `description="DEBIT ADVICE SR - (INCLUSIVE OF GST RM 0.48)"`, `amount=Decimal("8.48")`, `type="debit"`, `signed_amount=-8.48` for the reconciler.

### Sample data + tests

**`backend/sample_data/maybank_2026_sample.txt`:** real extracted text from the March 2026 statement (`847673614_20260331_7244.pdf`). Sanitized: replace the account number digits with `XXXXXX-XXXXXX` and the customer name lines with `REDACTED`. Keep all transaction data intact.

**`backend/sample_data/maybank_2018_sample.txt`:** real extracted text from the March 2018 statement (`1078593294_20180331_7244.pdf`). Same sanitization.

**`backend/tests/test_parser_maybank.py`:** rewritten. Tests:

1. `test_can_parse_detects_maybank` — both real fixtures pass `can_parse`
2. `test_can_parse_rejects_tng` — synthetic TnG-shape text fails (uses the real TnG fixture or a TnG-marker stub)
3. `test_can_parse_rejects_aeon` — synthetic AEON-shape text fails
4. `test_can_parse_rejects_just_maybank_word` — text containing `"MAYBANK"` but neither `"Malayan Banking Berhad"` nor `"URUSNIAGA AKAUN"` fails
5. `test_extract_period_month_2026` — March 2026 fixture → `"2026-03"`
6. `test_extract_period_month_2018` — March 2018 fixture → `"2018-03"`
7. `test_century_inference` — `01/01/26` → 2026; `01/01/18` → 2018; `01/01/85` → 1985 (boundary check)
8. `test_parses_2026_format` — March 2026 fixture parses all transactions; assert count, key field values for the first and last transaction (date, amount, type, description includes merchant)
9. `test_parses_2018_format` — March 2018 fixture parses all transactions; the GST column is correctly skipped
10. `test_debit_sign_detection` — `442.00-` → `transaction_type="debit"`, amount=`Decimal("442.00")`
11. `test_credit_sign_detection` — `500.00+` → `transaction_type="credit"`, amount=`Decimal("500.00")`
12. `test_multi_line_description_joining` — a transaction with 2-3 detail lines produces `"TYPE_LABEL - LINE1 LINE2 LINE3"` (collapsed whitespace)
13. `test_no_detail_lines` — a transaction with 0 detail lines produces `description == type_label` (no trailing `" - "`)
14. `test_skips_repeated_page_headers` — multi-page statement (real fixture) does not produce phantom transactions from page-2+ header repeats
15. `test_external_reference_is_none` — no per-tx IDs available
16. Real-fixture test (skip-if-missing) at `backend/tests/fixtures/real/maybank_savings.pdf` — assert >0 transactions parse, period_month matches the file's known period.

### Reconciler — `app/services/reconciler.py` extension

Add a fourth dispatch arm to `reconcile_statement`:

```python
elif _MAYBANK_MARKER in text and _MAYBANK_MARKER_2 in text:
    rows, headers = _extract_maybank_data(text)
```

Where `_MAYBANK_MARKER = "Malayan Banking Berhad"`, `_MAYBANK_MARKER_2 = "URUSNIAGA AKAUN"`, and the helper returns:

- `rows`: `list[{"signed_amount": float, "balance": float}]` — same shape as TnG (per-row balance present). Sign convention: `+amount` for credit (incoming, increases balance), `-amount` for debit (outgoing, decreases balance). This matches the natural sign suffix in the source (`+`/`-`).
- `headers`: `{"beginning": float, "ending": float | None}`:
  - `beginning`: parsed from the line after `"BEGINNING BALANCE"` (always present)
  - `ending`: parsed from the line after `"ENDING BALANCE :"` if present (2018 format only); `None` for 2026 format

**Checks run:**

1. **Count check** (existing `_check_count`) — verifies row count matches transaction count in the DB.

2. **Per-row check** (existing `_check_per_row`) — for each transaction, verifies `prev_balance + signed_amount == this_balance`. Seed with `headers["beginning"]`. Tolerance `0.01` (same as TnG).

3. **Statement-level check** (new inline logic in this dispatch arm):
   - Always: verify `headers["beginning"] + sum(signed_amounts) == final_running_balance` (where `final_running_balance` is `rows[-1]["balance"]`). Tolerance `0.01`.
   - If `headers["ending"]` is not None (2018 format): additionally verify `final_running_balance == headers["ending"]`. Tolerance `0.01`.

All three checks must pass for `needs_review = False`. The `reconcile_note` describes which check failed if any. `checks_run` includes all attempted checks.

The new helper `_extract_maybank_data` is hardcoded in `reconciler.py`. Future banks needing similar treatment will add their own helpers; if a fifth bank shows up we'll consider externalizing.

### Reconciler tests extension

Append to `backend/tests/test_reconciler.py`:

- `test_reconcile_maybank_2026_passes` — synthetic Maybank-shape text + matching DB rows, all checks pass.
- `test_reconcile_maybank_2018_passes` — synthetic 2018-format text (with explicit ENDING BALANCE) + matching DB rows, all three checks (count, per-row, statement) pass.
- `test_reconcile_maybank_per_row_mismatch_flags` — synthetic text with one balance line tweaked → `ok=False`, note mentions per-row.
- `test_reconcile_maybank_statement_mismatch_flags` — synthetic text where running balances are internally consistent but `ENDING BALANCE` doesn't match → `ok=False`, note mentions statement.
- Real-fixture test (skip-if-missing) using one Maybank PDF — assert reconciliation passes cleanly.

## Phase 2: Reprocess

### `backend/scripts/reprocess_maybank.py` — new

Mirrors the structure of `reprocess_tng.py` and `reprocess_aeon.py`:

1. Get the Maybank account (`bank='maybank'`). Create one if it doesn't exist (auto-discovery during fetch may not have created it yet; first reprocess is the canonical creation point).
2. Delete existing Maybank transactions: `DELETE FROM transactions WHERE account_id = <maybank_id>`.
3. Find all candidate statements. Strategy: filter on `bank IN ('unknown', 'maybank')` AND a Maybank-shape filename predicate. Maybank PDFs use the format `{accountnum}_{YYYYMMDD}_{lastdigits}.pdf` (e.g., `847673614_20260331_7244.pdf`). The discriminating signal is the trailing 4-digit segment matching the user's account-number suffix `_7244.pdf`. SQL must parenthesize the OR to keep predicate precedence correct:
   ```sql
   SELECT * FROM statements
   WHERE bank IN ('unknown', 'maybank')
     AND (filename LIKE '%_7244.pdf' OR filename LIKE '%maybank%')
   ORDER BY id
   ```
   For each candidate, do a content-level confirmation by running `MaybankParser.can_parse(text)` after decryption — this prevents accidentally claiming an unrelated PDF that happens to match the filename pattern. Skip any that don't pass.
4. For each: open with `PDF_PASSWORD_MAYBANK`, run new Maybank parser, dedup via broad key only (no refs), insert transactions, update `Statement.bank='maybank'` and `period_month`.
5. Run `RecurringDetector` once at end.

Idempotent — running twice produces the same end state.

### Backfill reconciliation flag

Re-run the existing `backend/scripts/reconcile_existing.py` after `reprocess_maybank.py`. No new script needed. The reconciler's new Maybank arm activates automatically.

### Manual smoke

After both scripts:
- `SELECT COUNT(*) FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE bank='maybank')` should be in the low-to-mid thousands across 61 statements (avg ~30-50 tx/month × 61 months).
- `SELECT COUNT(*) FROM statements WHERE bank='maybank'` should be 61.
- `SELECT COUNT(*) FROM statements WHERE bank='maybank' AND needs_review=1` should be small — single digits expected. Each one investigated manually (open the PDF, eyeball whether the reconciler is right).

## Testing Strategy Summary

| Phase | Automated | Manual |
|---|---|---|
| 1 | Unit tests for Maybank parser (16 tests) + reconciler extension (5 tests including real-fixture) | Visual verification: spot-check 2–3 statements via `replay_statement.py` after parser lands. |
| 2 | None — script's correctness validated by the reconciler's pass on its output. | After scripts run, query `needs_review` count; spot-check any flagged statements. |

## Risks & Open Questions

- **GST column tolerance.** The 2018-format GST line (e.g., `"SR"`) sits between the type label and the amount. The walk-forward "first signed-amount line" logic skips it naturally, but the GST line might end up included in `type_label` if naively concatenated. Mitigation: `type_label` is just the *first* non-empty line after the date; the GST line is the *second* non-empty line and gets discarded by the walk-forward to find the amount. Real-fixture test (`test_parses_2018_format`) catches any slip.

- **Trilingual page-header repeats.** Pages 2+ repeat the column-header block (BM/Chinese/English × multiple labels = ~12 lines per repeat). The "skip chunks where type_label is a known header token" logic handles this, but the list of header tokens is hardcoded. If Maybank changes a header label spelling, parser breaks silently for that statement until reconciliation flags it. Acceptable risk: real-fixture tests across 2018 and 2026 cover the observed labels.

- **Multi-line descriptions and the `*` marker.** Some detail lines end with `*` (e.g., `"SITTAL CARPARK SDN.*"`). The asterisk has unknown semantics (truncation marker? continuation?) and is preserved as-is in the joined description. Acceptable: it's user-facing text, not a parser concern.

- **Dates with 2-digit years past 2069.** The century-inference rule treats `70-99` as 19YY. Won't matter for 50+ years; flagged for completeness.

- **Reprocess script account discovery.** If no `Account(bank='maybank')` row exists yet (because the fetch path hasn't run successfully on a Maybank statement), the script must create it. Use `account_number` from one of the parsed statements if available; otherwise placeholder `"maybank-savings"`. This mirrors what TnG and AEON reprocess scripts do.

- **0.01 tolerance might mask real bugs.** Same trade-off as TnG and AEON. If every transaction is off by a consistent fraction, cumulative error eventually breaks the statement-level check. Acceptable for now.

- **`*` and GST suffix in old-format type labels.** Old-format type labels sometimes have trailing GST tags like `"DEBIT ADVICE     SR"` (GST tag inline rather than on a separate line). The type_label captures it as-is; this is OK for the description but means description text varies between eras. Acceptable: description is user-facing and not used for dedup matching beyond the broad key.

- **Filename-based statement selection in reprocess.** Uses `filename LIKE '%_7244.pdf'` which is the user's specific account number suffix. For a multi-user system this would need to be account-aware; for the single-user MVP it's fine. The fallback `filename LIKE '%maybank%'` covers any future Maybank PDF that doesn't follow that naming convention.
