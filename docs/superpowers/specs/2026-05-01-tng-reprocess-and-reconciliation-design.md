# TnG Reprocess + Reconciliation Layer — Design

**Date:** 2026-05-01
**Status:** Approved (pending spec review before plan)
**Goal:** Two adjacent pieces of work that should land together before adding any new bank parser:
1. Reprocess the existing 760 TnG transactions through the latest parser so descriptions reflect today's hardening fixes.
2. Add a reconciliation layer that catches silent parser drift on every statement going forward (and backfills the flag onto existing statements).

## Context

The TnG parser was substantially hardened in this session via a visual stress test against the 60-page annual statement: six parser bugs identified and fixed (DUITNOW_RECEI/VEFROM rejoin, no-whitespace ref strip, pure-letter-name preservation, 10+ digit ref strip, Cashback credit detection, type-column-aware credit detection that no longer marks `Payment Card Reload` as credit). The 760 transactions currently in the database were parsed before some of these fixes — their descriptions are stale.

In parallel, the deeper question — *"how do we know the parser isn't silently producing wrong numbers six months from now?"* — surfaced. Today there is no runtime guardrail against parser drift. A bug that skips one row and double-counts another would balance out at the totals level and ship undetected. This is the single largest long-term operational risk identified in the methodology research; closing it before adding more bank parsers means every future bank inherits the safety net for free.

A practical spike in the same session validated `Page.find_tables()` (PyMuPDF, already a dependency) as a column-aware extraction path: 32/32 of our existing TnG statements parsed to the same row count as the regex parser (984/984 transactions total). That spike makes `find_tables()` a strong candidate as a reconciliation side-channel — it returns balance columns the regex parser strips, giving us cheap arithmetic-based checks without modifying the regex parser itself.

## Architecture & Phase Sequencing

Two phases, sequenced so the reprocess validates against the new reconciliation layer:

**Phase 1 — Schema + reconciler service.** Add `Statement.needs_review: bool` and `Statement.reconciliation_note: str | None` columns. Build `app/services/reconciler.py` with one public function `reconcile_statement(stmt_id, db)` returning a `ReconcileResult`. Hook it into the end of `_process_fetched_pdf` and `upload_statement` so every new statement gets reconciled.

**Phase 2 — Reprocess + backfill.** Delete all existing TnG transactions, re-parse the 32 statements with today's parser, re-run categorizer and recurring-detector. Then run a one-shot `scripts/reconcile_existing.py` over every Statement row to backfill the `needs_review` flag for both the freshly-reprocessed TnG data and any other historical statements.

**Dependency chain:** Phase 1 → Phase 2. Phase 1 alone gives us forward protection; Phase 2 lands the data cleanup and verifies Phase 1 against real history.

## Scope Exclusions

Deliberately out of scope for this work:

- UI surfacing of `needs_review` (Settings/Statements view). The backend flag lands now; frontend exposure comes after we have a Statements page or once `needs_review` count grows large enough to need attention.
- The full `find_tables()`-based parser refactor. We are using `find_tables()` purely as a reconciliation cross-check, not replacing the regex parser.
- Reconciliation for Maybank / CIMB / Hong Leong / AEON / Public Bank. The reconciler is generic but balance-column indices and any per-bank quirks are unknown until we have those PDFs and can implement their parsers.
- LLM fallback tier. Mentioned in the methodology research as a Tier 2 extractor invoked when reconciliation fails. Worth building, but the gating mechanism (this reconciler) needs to land first.
- Migration of existing Account.bank values or other DB-level fixes unrelated to TnG/reconciliation.

## Phase 1: Reconciler

### Schema changes

`backend/app/models.py` — `Statement`:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `needs_review` | `Mapped[bool]` | `False` | Set to `True` when any reconciliation check fails. |
| `reconciliation_note` | `Mapped[str \| None]` | `None` | Short human-readable failure reason, e.g. `"row count mismatch: regex=62, tables=63"` or `"closing balance mismatch: opening + Σ = 132.05, expected 132.06"`. |

Applied via `ALTER TABLE statements ADD COLUMN ...` on the existing dev DB; lifespan `Base.metadata.create_all` handles fresh DBs.

### New service: `app/services/reconciler.py`

Public surface:

```python
class ReconcileResult:
    ok: bool
    note: str | None        # Failure reason when ok=False; skip reason when ok=True (e.g. encrypted PDF we can't open). None means everything passed.
    checks_run: list[str]   # ["count", "statement", "per_row"] subset

def reconcile_statement(stmt_id: int, db: Session) -> ReconcileResult: ...
```

The integration code only sets `needs_review = True` on `not result.ok`, so a skipped reconciliation (e.g. encrypted PDF, file missing) does not flag the statement — it just leaves `needs_review` at its default `False`. The skip is recorded in `result.note` for audit purposes only.

Internal flow:
1. Load the `Statement` row by id; locate the file at `Statement.file_path` (relative to `BACKEND_ROOT`).
2. Open the PDF with PyMuPDF. If `doc.is_encrypted`, sender info isn't stored on the Statement so we can't do an exact lookup. Iterate every value in `SENDER_PASSWORDS` and call `doc.authenticate(pw)`; the first non-zero return value wins. If none authenticate, return `ReconcileResult(ok=True, checks_run=[], note="encrypted: no configured password")` — we cannot reconcile what we cannot read, but absence of evidence is not evidence of failure, so this does not flag `needs_review`.
3. Walk every page's `find_tables().tables`, extract data rows (skip header rows whose first cell is one of `{"Date", "Trans No.", "Transaction No.", "Status"}` or whose first line doesn't look like a date or trans-number ID).
4. Build a normalized list `tables_rows: list[dict]` with `{date, signed_amount, balance | None}`. Sign is positive for credits, negative for debits — credit detection mirrors the parser's logic so the two sources agree on direction.
5. Run the three checks in order; the first failure short-circuits and is returned.

### Three checks

**Check 1 — Count cross-check (universal).**
- Required input: `len(tables_rows)` and `len(db.query(Transaction).filter_by(statement_id=stmt_id).all())`.
- Pass condition: counts equal.
- Failure note: `"row count mismatch: db={db_count}, tables={table_count}"`.

**Check 2 — Statement-level balance (only when ≥1 row in `tables_rows` has a `balance` value).**
- `opening_balance` = balance of the first row + the negative of its signed amount (back out the first row's effect).
- `closing_balance` = balance of the last balanced row.
- Pass condition: `abs(opening + Σ(signed_amounts_with_balance) - closing) <= 0.01`.
- Failure note: `"closing balance mismatch: opening={o}, sum={s}, expected={c}, computed={o+s}"`.

**Check 3 — Per-row monotonic (only on rows where both `i` and `i+1` have balances).**
- For each consecutive balanced pair: `abs(tables[i].balance + tables[i+1].signed_amount - tables[i+1].balance) <= 0.01`.
- Pass condition: every consecutive pair satisfies the relation.
- Failure note: `"per-row balance mismatch at row {i+1}: prev={p}, signed_amount={a}, expected={p+a}, got={t}"`.

A statement that has no balance data on any row (e.g., a TnG legacy statement with only an offline section) skips checks 2 and 3 and relies on check 1 only. The `checks_run` field on the result records which checks were applicable.

### Integration into the upload paths

`_process_fetched_pdf` (`app/routers/email.py`) and `upload_statement` (`app/routers/upload.py`):

After the existing `db.commit()` that persists transactions:

```python
result = reconcile_statement(stmt.id, db)
if not result.ok:
    stmt.needs_review = True
    stmt.reconciliation_note = result.note
    db.commit()
    logger.warning("reconcile failed for statement %d: %s", stmt.id, result.note)
```

The reconcile call MUST NOT raise on a check failure — failure is an in-band `ok=False` result. Genuine errors (file missing, unreadable PDF) raise; the caller does not catch — those should bubble up to surface as 500s during dev so we notice. (The encrypted-PDF skip is `ok=True`, not a raise.)

### Tests

`backend/tests/test_reconciler.py`:
- Unit tests with a hand-constructed `tables_rows` list bypassing the PDF read:
  - Count match + balances ok → `ok=True`, `checks_run=["count","statement","per_row"]`.
  - Count mismatch → `ok=False`, note mentions the counts.
  - Closing balance off by 0.05 → `ok=False`, note mentions `statement` check.
  - Per-row off at row 3 → `ok=False`, note mentions `per_row` check at row 3.
  - All-rows-no-balance (offline-only) → `ok=True`, `checks_run=["count"]`.
  - 0.01 rounding tolerance accepted.
- One integration test that exercises the real TnG fixtures via the existing `_real_pdf_helper` skip-if-fixture-missing pattern: the annual statement should reconcile cleanly.

## Phase 2: Reprocess + backfill

### Reprocess script

`backend/scripts/reprocess_tng.py` — same body as the one-off we ran in this session:
1. Get the TnG account.
2. `DELETE FROM transactions WHERE account_id = <tng_id>`.
3. For each `Statement` with `bank='tng'`: open PDF (with password if encrypted), parse with current `TnGParser`, dedup-on-insert against the in-progress set (using `external_reference` and broad-key with promote — same logic as the routers), insert.
4. Run `RecurringDetector` once at the end.
5. Print a summary line.

The script is committed because it's repeatable (will be useful again the next time we ship parser fixes that affect existing data). Idempotent — running it twice produces the same end state.

### Backfill reconciliation flag

`backend/scripts/reconcile_existing.py`:
1. For every `Statement` row in the DB, call `reconcile_statement(stmt.id, db)`.
2. If `not result.ok`, set `needs_review` and `reconciliation_note`, commit.
3. Print a summary: `{n_total} statements scanned, {n_flagged} flagged, {n_skipped_encryption} skipped (encryption), {n_skipped_no_file} skipped (file missing)`.

Run order: reprocess script first, then reconcile_existing — so the flag reflects the freshly reprocessed data, not the stale pre-reprocess state.

### Manual smoke after Phase 2

After both scripts run, manually verify:
- TnG transaction count is in the same ballpark as before (760 ± a few from the parser-fix improvements that previously over-collapsed rows).
- `SELECT COUNT(*) FROM statements WHERE needs_review = TRUE` is small (single digits expected; if it's >5 we have a bug).
- Spot-check one flagged statement: open the PDF, check whether the flag is right or whether the reconciler has a false positive.

## Testing Strategy Summary

| Phase | Automated | Manual |
|---|---|---|
| 1 | Unit tests for `reconciler.py` covering all three checks, the offline-only path, and the 0.01 tolerance. Integration test against a real TnG fixture (skip-if-missing). | None expected. |
| 2 | The reprocess script's correctness is validated by the reconciliation layer running against its output — if the parser is right, every reprocessed statement reconciles cleanly. | After both scripts: `SELECT COUNT(*) FROM transactions WHERE account_id IN (...) AND external_reference IS NOT NULL` ≈ 760. `SELECT COUNT(*) FROM statements WHERE needs_review = TRUE` ≈ 0–3. |

## Risks & Open Questions

- **Encrypted statement reconciliation.** We can only reconcile what we can decrypt. Today only TnG has a configured password. AEON statements (also encrypted, no password yet) will skip checks 2 and 3 silently. The skip is recorded in `checks_run` so we can audit later, but the reconciler does not flag those as "needs review" — that would be noise, not signal. Acceptable.
- **Sign convention for credits in `tables_rows`.** The reconciler's credit/debit detection must mirror the parser's, otherwise reconciliation flags every credit as a balance mismatch. The credit-detection logic (a list of type prefixes: `DUITNOW_RECEI`, `RECEIVE`, `RELOAD`, `REFUND`, `CASHBACK`) is extracted out of `tng.py` into a shared `is_credit_type(type_text: str) -> bool` helper that both the parser and the reconciler call. A regression test walks the helper against a fixture list of every observed type string from the real data and asserts the expected sign.
- **PyMuPDF table detection variability.** `find_tables()` is heuristic and could in theory miss a row on a future TnG layout. The count cross-check would then flag every such statement. That's the desired behavior — fail loud, investigate. The risk is a false-positive flag flood if TnG ships a layout that defeats `find_tables()`; the mitigation is the `reconciliation_note` field, which makes the failure mode visible enough to investigate quickly.
- **Per-row check on legacy online section.** Legacy online rows have a Card Balance column, but the running balance only reflects online transactions — offline transactions in the same period happened against the same wallet but are listed in a separate table without their own balance column. Treating online and offline as one timeline would break per-row checks because the balance "jumps" wherever an offline transaction occurred between two online ones. Mitigation: per-row checks run online-section-only; offline rows contribute to the count cross-check only.
- **0.01 rounding tolerance might mask real bugs.** A consistently-off-by-0.01 parser bug would slip past per-row checks. Mitigation: the statement-level check uses the same tolerance, so if every row is off by 0.01 in the same direction, the cumulative error compounds and the statement-level check catches it.
