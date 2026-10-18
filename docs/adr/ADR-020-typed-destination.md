# ADR-020: Typed Destination Columns — What Is Typed, and the Gate in Front of It

## Status
Accepted — 2026-10-05. Implements `docs/improvement-report.md` D5 (plan finding F1).

## Context

The report said every one of the 24 semantic types lands in a TEXT column and
that a pre-insert cast gate had yet to be built. The code had moved on (F1):
`normio/storage_types.py` already types NUMERIC, MONEY and BOOLEAN natively on
both engines, `typed_destination_columns` defaults to true, and `coerce` is the
pre-insert cast. The comments in both destination connectors still said
"every value is TEXT/String", which was the state before `storage_types`.

Decision #8 is the constraint every choice here answers to: a failed value's
ORIGINAL string always lands in the cell, and a value a typed column cannot
hold must never reach `INSERT`, because one rejected row aborts the chunk's
transaction, and with it the error rows that would have explained it.

## Decision

**What is typed.** NUMERIC and MONEY become exact decimals, BOOLEAN becomes a
boolean. Types per engine:

| semantic type | Postgres | ClickHouse |
|---|---|---|
| NUMERIC | `NUMERIC` (unbounded) | `Decimal(38,9)` |
| MONEY | `NUMERIC(38,4)` | `Decimal(38,4)` |
| BOOLEAN | `BOOLEAN` | `Bool` |

Everything else, key columns included, stays TEXT/String.

**The gate.** `storage_types.coerce` runs on every value bound for a typed
column. It returns a clean typed value or `(None, error)`, and never raises. A
value that will not cast is written as NULL, and the error goes into the job's
error rows. The gate checks against the *target column's* precision and scale,
taken from the engine's type string. A finite number with more integer digits
than the column holds (for example `1e30` into `Decimal(38,9)`, or `10^40` into
`NUMERIC(38,4)`) is therefore a cast failure, not an INSERT failure. Before D5
it passed the gate, because the gate only knew the semantic type. The check is
made after rounding to the column's scale (`99.995` needs three integer digits
in a scale-2 column), and the returned value is not rounded: the database
rounds, the gate invents no precision. "Unbounded" Postgres `NUMERIC` still has
the documented ceiling of 131072 digits before the point; a finite Decimal past
it (`1e999999999`) is a cast failure too. The executor passes the job's engine
(source and destination are always the same engine).

**Cast failures are INVALID, not AMBIGUOUS.** A value that is not a number is
not a question anyone can answer, so it is not queued for adjudication
(ADR-018, Q14). The original string is preserved in the error row.

**DATE and DATETIME stay TEXT, with typed bounds beside them (amended
2026-10-14, user decision of 2026-10-06, PART1 D5.3).** They normalize to EDTF
values that can be partial (`1990`, `1990-03`) when that is all the source
stated. A SQL DATE column cannot hold a partial date. Typing it would either
turn year-only dates into NULL or invent a month and day; both break
"precision is preserved, never invented". So the TEXT column keeps the value as
stated, and two typed companions, `<col>__from` and `<col>__to`, hold the first
and the last day of the stated period: `1990` is 1990-01-01 to 1990-12-31,
`1990-03` is 1990-03-01 to 1990-03-31, a full date is itself twice, an EDTF
range is its own bounds (an open end stays NULL). A bound is a range, not a
point, so nothing is invented, and SQL can filter and sort on it. They are
Postgres `DATE` and ClickHouse `Date32`. Only a clean answer gets bounds; an
AMBIGUOUS or INVALID value gets NULL in both. A bound outside the column's
range (ClickHouse Date32: 1900-01-01 to 2299-12-31) is NULL plus an error row,
through the same gate as numbers. A DATETIME's bounds are the dates of its
period; its time stays in the TEXT column. Key columns get no companions, like
the other typed columns.

## Alternatives considered

- **Typed DATE plus the EDTF original in a companion column** (`<col>__edtf`).
  Rejected for the bounds above: the typed column would still be NULL for
  every partial value, while bounds give every clean value, partial or not, a
  queryable range.
- **Rebuilding the gate as a separate layer.** Rejected: `coerce` already sits
  at the one place every typed value passes through.

## Consequences

- The same source column can round differently on the two engines (Postgres
  NUMERIC is unbounded; ClickHouse is 38 digits with 9 after the point). This
  is recorded at `_CH_TYPES` in `storage_types.py`, with its `ponytail:`
  ceiling (Decimal256).
- *Live verification* (`defects/LOCAL_VERIFY.md`, D5): a clone with planted
  out-of-range and non-numeric values completes, keeps its typed columns, and
  reports the bad values in error rows, on both real engines.
