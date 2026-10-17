# ADR-021: Disguised Missing Data in a Clone — Reported With Exact Counts, Applied Only When Confirmed

## Status
Accepted — 2026-10-14. Implements `docs/improvement-report.md` D4 in the clone path (PART1 D4.1,
D4.2). The detector itself is `normanalysis/disguised_missing.py` (D4, Phase 3), which until now
nothing called.

## Context

Part 1 D4: a column that is 97% dates and 3% `N/A`, `-999` and `unknown` "has no way to say so",
and the fix is to model disguised missing data "as a first-class outcome" that reports "which
cells are non-conforming", with `MissingKind` receiving the output. The detector existed as a
library function over `value -> count`; no clone, plan or report used it, and no cell ever got a
`MissingKind` from it.

## Decision

**Report from the counts the clone already has.** Phase 2 knows every cell's status. Per
configured column it counts each value the type rejected (INVALID) and the cells that conformed;
at the end of the table the detector's rule (`disguised_missing.candidates`) runs on those exact
counts. No second read of the source, no validation run twice. The result is stored per column in
the job's quality report, `quality[table][column]["disguised_missing"]`: value, exact count, and
the missing-value table's hint or `null`.

**Apply only what a person confirmed.** A candidate is not a verdict: `empty` in a DATE column is
most likely a disguised null, and the detector cannot know. The job field `confirmed_missing`
(`{table: {column: [value, ...]}}`, at creation or through `PATCH .../plan`) lists exact values.
In a later run each such value is MISSING (`MissingKind.UNKNOWN_VALUE`), never dispatched; the
cell is NULL and the error row keeps the original, as for any value that means missing. Exact
string match only: nothing is matched loosely, nothing is inferred from a neighbour.

**Values the missing-value table already names** (`N/A`, `-`, `null` ...) are MISSING through the
Dispatcher before any normalizer sees them, as before; they are not reported again here. Since
PART1 N5, a table token that a discriminating type also reads as a value (`NA`, Namibia) is
AMBIGUOUS and goes to the review queue instead.

## Limits

- `-999` and other in-range magic numbers stay out of reach: a valid number is not a failing
  value, and calling one missing by its frequency alone would be a guess. A frequency model
  (`ptype`) is the upgrade path, as the detector's own `ponytail:` note says.
- Distinct failing values kept per column are bounded (`_FAILING_VALUES_KEPT`, `ponytail:`). A
  column with more is dirty data, not disguised nulls, and the rule then reports only the values
  the missing-value table names.
- The report is per job; confirming a value applies from the next job created with it.
