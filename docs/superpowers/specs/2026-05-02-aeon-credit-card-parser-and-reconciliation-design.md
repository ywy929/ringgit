# AEON Credit Card Parser + Statement-Level Reconciliation — Design

**Date:** 2026-05-02
**Status:** Approved (pending spec review before plan)
**Goal:** Add a working AEON Credit Card (BC / `AMP VISA CLASSIC`) parser and extend the reconciler to handle credit-card-style statement-level checks. Reprocess the 31 existing encrypted-stub statements through the new parser.

## Context

After landing TnG end-to-end and the reconciliation layer, the next bank with available data is AEON. The user's gmail inbox has **39 encrypted AEON PDFs** that have been sitting as `bank='unknown'` stubs since the Phase-2 backfill — 31 are BC (Big Card / AMP VISA CLASSIC credit card) and 8 are VP (Visa Platinum prepaid card). Both are decryptable with the password already configured in `PDF_PASSWORD_AEON`.

A spike confirmed three things:

1. **The two products are structurally different.** BC is a credit card statement (Previous Balance → Charges − Payments → Current Balance). VP is a prepaid card statement (separate Credit Transaction(s) and Transaction(s) Spent sections). The user has chosen to scope this work to BC only — the VP card is incidental (used to pay back the credit card to earn points), not a primary tracking concern.

2. **`Page.find_tables()` does not work for AEON the way it did for TnG.** AEON's PDF transaction table has no row-level geometric separators, so find_tables produces a single 4-column "row" with all transactions mashed into newline-separated strings. Worse, the columns drift out of length alignment because header rows like `"YOUR PREVIOUS STATEMENT BALANCE"` and card-number headers interleave in the description column. We must fall back to anchor-based text parsing — the same approach that works for the legacy TnG format.

3. **Credit card statements have no per-row running balance.** The reconciler's per-row monotonic check doesn't apply. Statement-level math is the only arithmetic check available, and the statement header conveniently provides Previous Balance, Total Charges of the Month, and Total Current Balance — perfect for the check.

The existing `AEONParser` is the same fictional-sample-tuned regex as the original TnG parser was. Full rewrite expected.

## Architecture & Phase Sequencing

Two phases, sequenced so each validates against the next:

**Phase 1 — Parser + reconciler dispatch.** Rewrite `app/services/parsers/aeon.py` from scratch using anchor-based parsing. Extend `reconcile_statement` with a third format-detection arm for AEON. The reconciler runs count check + statement-level balance (no per-row).

**Phase 2 — Reprocess.** New `backend/scripts/reprocess_aeon.py` that finds the 31 BC statements (`bank='unknown'`, `filename LIKE '%BC_STMT%'`), decrypts with `PDF_PASSWORD_AEON`, parses with the new parser, dedups via broad key (no refs available), inserts. The existing `reconcile_existing.py` script (committed as part of the TnG reconciliation work) re-runs at the end to backfill the `needs_review` flag — including against the freshly-parsed AEON data.

**Dependency chain:** Phase 1 → Phase 2.

## Scope Exclusions

- **VP prepaid parser.** Out of scope. The 8 VP statements stay as `bank='unknown'` stubs. Their PDFs are saved on disk; user can investigate manually if needed.
- **`find_tables()`-based parsing for AEON.** Verified doesn't work cleanly; we use anchor-based text parsing instead.
- **Per-row reconciliation for AEON.** Doesn't apply to credit card statements (no per-tx running balance).
- **Refactoring `is_credit_type` to be bank-agnostic.** AEON uses a different signal (literal `"CR"` line in the chunk, not a type-column lookup). Keep AEON's sign detection local to its own extractor.
- **External per-bank reconciler config.** Format dispatch stays hardcoded. We'll externalize when there are 4+ banks; today there are 2.
- **Other AEON-related transaction features** (loyalty points statement, AEON Wallet receipts, marketing PDFs in the 4 readable AEON-marker files we found). Out of scope.

## Phase 1: Parser

### `app/services/parsers/aeon.py` — full rewrite

**`bank_id`:** `"aeon"` (unchanged — matches the existing `Account` row).

**`can_parse(text)`:** matches when text contains BOTH `"AEON CREDIT SERVICE"` AND `"Total Charges of the Month"`. The second clause is the credit-card-specific discriminator that rejects VP prepaid statements. (VP also has a "Previous Statement Balance" line — actually `"Your Previous Statement Balance"` — so checking for that is NOT sufficient. `"Total Charges of the Month"` is a credit-card billing-cycle concept that VP's prepaid model has no analog for.)

**`extract_period_month(text)`:** matches `r"Statement Date[\s\S]*?:\s*Tarikh Penyata\s*\n(\d{2})\s+(\w{3})\s+(\d{4})"` (the bilingual label block) → `"YYYY-MM"`. Fallback regex without the bilingual label as defensive measure.

**`parse(text)`:** anchor-based extraction.

The anchor pattern: TWO consecutive lines, each matching `^(\d{2})\s+(\w{3})\s+(\d{4})$` (Posting Date and Transaction Date).

For each anchored chunk (anchor pair → next anchor pair OR end of transactions section):

| Field | Source |
|---|---|
| `date` | The Transaction Date (line 2 of the chunk), converted from "DD MMM YYYY" to ISO "YYYY-MM-DD" |
| `description` | All lines between the date pair and the amount line, EXCLUDING any standalone `"CR"` line. Joined with spaces, whitespace-collapsed. |
| `amount` | The last line in the chunk matching `^[\d,]+\.\d{2}$`, parsed as float (commas stripped) |
| `type` | `"credit"` if any line in the chunk equals exactly `"CR"`, otherwise `"debit"` |
| `external_reference` | `None` — AEON doesn't expose per-transaction unique IDs in the PDF |

Transactions section is bounded by:
- **Start:** the line "Transaction Details" (the column header) — anything before it is header/marketing.
- **End:** any line containing `"YOUR PREVIOUS STATEMENT BALANCE"` (the totals/footer that appears AFTER all real transactions in some statements) OR end-of-text.

Header rows that interleave (`"YOUR PREVIOUS STATEMENT BALANCE\n2,138.72"`, `"4726980298444801 MR YEAP WENG YEOW"`) are NOT anchors — they don't match the date pattern — so they're naturally excluded.

### Sample data + tests

**`backend/sample_data/aeon_sample.txt`:** synthetic line-by-line dump matching the real PDF's text shape. Use 3 transactions: one debit purchase, one CR credit (payment), and one multi-line description (defensive — even though real samples haven't shown wrapping, we want the parser to handle it).

**`backend/tests/test_aeon_parser.py`:** rewritten. Tests:
- `test_can_parse_detects_aeon_credit_card` — sample text passes
- `test_can_parse_rejects_vp_prepaid` — synthetic VP-shape text fails (uses VP-specific markers, no "Previous Statement Balance")
- `test_can_parse_rejects_other` — synthetic Maybank-shape text fails
- `test_extract_period_month` — correct `YYYY-MM` from the bilingual Statement Date block
- `test_parses_debit_purchase` — non-CR transaction → `type="debit"`, correct amount, description contains the merchant
- `test_parses_credit_payment` — CR transaction → `type="credit"`, correct amount, description does NOT contain "CR"
- `test_external_reference_is_none` — no per-tx IDs available
- `test_skips_previous_statement_balance_header` — header rows in description column don't produce phantom transactions
- Real-fixture test (skip-if-missing) at `backend/tests/fixtures/real/aeon_credit.pdf` — assert >0 transactions parse, period_month matches the file's known period.

### Reconciler — `app/services/reconciler.py` extension

Add a third dispatch arm to `reconcile_statement`:

```python
elif _AEON_MARKER in text:
    rows, headers = _extract_aeon_credit_data(text)
```

Where `_AEON_MARKER = "AEON CREDIT SERVICE"` and the helper returns:

- `rows`: `list[{"signed_amount": float, "balance": None}]` — same shape as TnG, just with balance always None. Sign convention: `+amount` for debit (purchase, increases balance owed), `-amount` for credit (CR, decreases balance owed).
- `headers`: `{"previous": float, "current": float}` — extracted via two regex matches anchored on the `"Previous Statement Balance"` and `"Total Current Balance"` labels and the RM-prefixed values that follow.

Note: the existing `_check_statement_balance` short-circuits to `ok=True` when no row has a balance (which is the AEON case). We DON'T reuse it — the AEON dispatch arm runs the statement-level check inline using `headers` directly. The existing `_check_per_row` correctly skips because all balances are None. Only the count check from the existing reconciler is reused.

Inline statement-level check:

```python
expected = headers["previous"] + sum(r["signed_amount"] for r in rows)
if abs(expected - headers["current"]) > 0.01:
    return ReconcileResult(ok=False, note=f"closing balance mismatch: previous={headers['previous']:.2f}, sum={sum_signed:.2f}, expected={headers['current']:.2f}, computed={expected:.2f}", checks_run=["count", "statement"])
```

Per-row check is skipped because all balances are None (existing logic handles this gracefully).

The new helper `_extract_aeon_credit_data` is hardcoded in `reconciler.py`. Future banks needing similar treatment will add their own helpers; if a fourth bank shows up we'll consider externalizing.

### Reconciler tests extension

Append to `backend/tests/test_reconciler.py`:
- Unit test against synthetic AEON text — verify both `rows` and `headers` extracted correctly, all checks pass.
- Real-fixture test (skip-if-missing) using one BC PDF — assert reconciliation passes cleanly OR flags with a known reason.

## Phase 2: Reprocess

### `backend/scripts/reprocess_aeon.py` — new

Mirrors the structure of `reprocess_tng.py`:

1. Get the AEON account (`bank='aeon'`).
2. Delete existing AEON transactions: `DELETE FROM transactions WHERE account_id = <aeon_id>` (count: 0 today, since none were ever parsed).
3. Find all candidate statements: `SELECT * FROM statements WHERE bank IN ('unknown', 'aeon') AND filename LIKE '%BC_STMT%' ORDER BY id`.
4. For each: open with `PDF_PASSWORD_AEON`, run new AEON parser, dedup via broad key only (no refs), insert transactions, update `Statement.bank='aeon'` and `period_month`.
5. Run `RecurringDetector` once at end.

Idempotent — running twice produces the same end state. The script is committed because it's the canonical way to apply parser fixes retroactively.

### Backfill reconciliation flag

Just re-run the existing `backend/scripts/reconcile_existing.py` after `reprocess_aeon.py`. No new script needed. The reconciler's new AEON arm activates automatically.

### Manual smoke

After both scripts:
- `SELECT COUNT(*) FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE bank='aeon')` should be a few hundred (depends on how many transactions across 31 statements).
- `SELECT COUNT(*) FROM statements WHERE bank='aeon'` should be 31 (the 8 VP stay as `unknown`).
- `SELECT COUNT(*) FROM statements WHERE bank='aeon' AND needs_review=1` should be small — single digits expected. Each one investigated manually (open the PDF, eyeball whether the reconciler is right).

## Testing Strategy Summary

| Phase | Automated | Manual |
|---|---|---|
| 1 | Unit tests for AEON parser (8 tests) + reconciler extension (synthetic + real-fixture) | Visual verification: spot-check 2–3 BC statements via `replay_statement.py` after parser lands. |
| 2 | None — script's correctness validated by the reconciler's pass on its output. | After scripts run, query `needs_review` count; spot-check any flagged statements. |

## Risks & Open Questions

- **`can_parse` ambiguity between BC and VP.** Both contain `"AEON CREDIT SERVICE"`. Mitigation: require BOTH that string AND `"Previous Statement Balance"` (which VP uses different casing for, and isn't a credit-card-specific concept regardless). A `test_can_parse_rejects_vp_prepaid` regression test pins this.

- **Multi-line descriptions.** The visible samples all have single-line descriptions, but real-world merchant names sometimes wrap. The parser's "all lines between dates and amount" logic handles this gracefully — multi-line descriptions get joined with spaces. Defensive but not load-bearing on observed data.

- **`_extract_aeon_header_balances` regex sensitivity.** The "Previous Statement Balance" / "Total Current Balance" labels are bilingual and may have different surrounding whitespace across statements. Plan: anchor regex on the English label, then walk forward to find the next `RM\s*[\d,]+\.\d{2}` value. Add a test against the real fixture to validate across all 31 statements (the real-fixture reconciler test will surface drift).

- **0.01 tolerance might mask real bugs.** Same trade-off as TnG: if every transaction is off by a consistent fraction, the cumulative error eventually breaks the statement-level check. Acceptable for now.

- **Period_month extraction from the bilingual label.** "Statement Date / Tarikh Penyata\n25 Apr 2026" — if the layout drift puts the date on a different line, regex needs adjustment. Real-fixture test catches this.

- **AEON Statement Date is the LAST day of the cycle, not the FIRST.** A 25 Apr 2026 statement covers transactions roughly 26 Mar 2026 to 25 Apr 2026. Recording `period_month="2026-04"` (from the statement date) is the right convention since each statement is named by its closing month, but worth knowing if the dashboard ever needs to be precise about cycle dates.

- **VP statements remaining as `unknown`.** A future "VP parser" task is plausible; today these stubs sit harmlessly. Their `file_path` is recorded so they're recoverable.
