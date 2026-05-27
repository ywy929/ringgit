# Ringgit — Personal Financial Analyzer

## Behavioral Guidelines

Reduces common LLM coding mistakes. Bias: caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.

### 2. Simplicity First
Minimum code that solves the problem. No features beyond what was asked, no abstractions for single-use code, no error handling for impossible scenarios. If 200 lines could be 50, rewrite it.

### 3. Surgical Changes
Touch only what you must. Don't "improve" adjacent code, don't refactor what isn't broken, match existing style. If you notice unrelated dead code, mention it — don't delete it. Remove imports/variables/functions that *your* changes orphaned; leave pre-existing dead code alone.

### 4. Goal-Driven Execution
Transform tasks into verifiable goals before coding:
- "Add a new bank parser" → "Fixture PDF + reconciliation test pass, prior fixtures stay green"
- "Fix a parser bug" → "Fixture reproducing it passes; all prior fixtures stay green"
- "Refactor X" → "`pytest tests/` all green before and after"

### Project-specific
Parsers are the highest-regression-risk area — anchor-based parsing is fragile to PDF format changes. See `~/PersonalVault/projects/ringgit-financial-analyzer/decisions/ADR-001-anchor-based-parsing.md` for the rationale.

---

See `~/PersonalVault/projects/ringgit-financial-analyzer/index.md` for architecture, ADRs, and supported-banks status.
