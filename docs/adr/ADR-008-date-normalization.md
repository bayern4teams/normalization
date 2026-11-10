# ADR-008: Date and Time Normalization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §43–§45 require ISO 8601 canonical output, explicit rejection of
silent locale guessing (`"01/02/03"` must not become an arbitrary date
without context), IANA timezone identifiers over ambiguous abbreviations
(`America/New_York` not `EST`), and non-Gregorian calendar support (Jalali,
Hijri) that preserves rather than erases the source representation.

`dateparser` (scrapinghub, BSD) is the mandated multilingual candidate per
§4.6. It supports 200+ language locales and remains, per research, the only
library handling genuinely global multilingual date parsing — alternatives
(`python-dateutil`) lack multilingual support entirely. Maintenance is
active (v1.4.2, August 2026).

`dateparser`'s permissive default settings will happily guess an
interpretation for ambiguous strings, which directly conflicts with §43's
conservatism requirement — the library must be configured, not trusted at
defaults.

## Decision

- **`dateparser`**, invoked with strict settings — **but with an important,
  empirically-verified caveat**: a spike in M0 (`spikes/04_dateparser_strict.py`)
  proved that `STRICT_PARSING=True` alone does **not** stop `dateparser`
  from guessing an interpretation for ambiguous input. `dateparser.parse("01/02/03",
  settings={"STRICT_PARSING": True})` still returns `2003-01-02` (an assumed
  MDY reading) with no locale context supplied at all — `STRICT_PARSING`
  only rejects *incomplete* dates (e.g. missing a day/month/year part), not
  *order-ambiguous* ones. This means the conservatism §43 requires **cannot
  be delegated to `dateparser`'s settings alone** — it must be enforced by
  our own wrapper logic:
  - If `context.locale` (and therefore an explicit `DATE_ORDER`) is
    available, pass it to `dateparser` and trust the result.
  - If `context.locale` is **not** available and the input is
    order-ambiguous (day/month both ≤12, format uses a separator that
    doesn't disambiguate), our `DateNormalizer` wrapper itself downgrades
    the result to `status: AMBIGUOUS` regardless of what `dateparser`
    returned — recording `dateparser`'s best-effort guess only in
    `assumption`, never in `parsed_date`.
  - `REQUIRE_PARTS=["day","month","year"]` and `STRICT_PARSING=True` are
    still set, because they do correctly reject genuinely incomplete input
    (e.g. a bare "March 2024" with no day) — just not order ambiguity.
- **Fast path**: `ciso8601` for values that already match ISO 8601 exactly
  — the common case in well-behaved source systems — avoiding
  `dateparser`'s heavier multilingual machinery entirely for those values
  (a deliberate performance optimization, §102).
- **No locale context and an ambiguous format (e.g. `MM/DD/YY` vs
  `DD/MM/YY` both plausible) → `status: AMBIGUOUS`**, with `parsed_date`
  left null or set to the best-effort value only alongside an explicit
  `assumption` field naming which order was assumed and a `confidence`
  well below the `NEEDS_REVIEW` threshold. This is never resolved silently.
- Output struct: `parsed_date` (ISO 8601), `source_locale`, `assumption`,
  `confidence`, `ambiguity`, plus for datetimes a timezone-aware ISO string
  or explicit UTC marker.
- **Timezones**: IANA identifiers preferred (`America/New_York`); bare
  abbreviations (`EST`, `CST`) are stored only when an IANA zone cannot be
  derived, and the fact that only an abbreviation is available is itself
  recorded as a warning.
- **Non-Gregorian calendars**: when `dateparser`'s calendar support
  converts Jalali/Hijri/etc. to Gregorian, the record retains
  `original_calendar`, `original_value` (untouched), `canonical_date`,
  `calendar_conversion_method`, and `confidence` — the source representation
  is never overwritten or discarded.

## Consequences

- The `ciso8601` fast path plus `dateparser` fallback means throughput on
  well-formed ISO data (the common case) is not gated by `dateparser`'s
  multilingual parsing cost.
- `AMBIGUOUS` is a common, expected, first-class status for date fields
  lacking locale context — this must be visible and actionable in the UI
  (Quality Dashboard, §93), not buried.
- `dateparser`'s pinned version participates in `env_id`; its locale data
  can change parsing behavior across releases.

## Revisit triggers

- `dateparser` maintenance status changes materially (tracked by the
  nightly drift job and periodic manual check, given the project's history
  of relying on volunteer maintenance).
- A source system's date locale becomes reliably determinable at the
  connector level (e.g. explicit column metadata) — wire that as a first-
  class `context.locale` input rather than a per-field manual override.

## Amendment 2026-10-17: a column's own values can state its day/month order

**Context.** Two people labelled real refused dates independently (PART1 D6.3,
REPORT §11.12). Each read a whole column one way: in Raha `rayyan`
`article_jcreated_at`, 38 distinct values can only be month first (`1/13/14`),
none can only be day first, and 320 cells were refused as AMBIGUOUS. A column
written by one system states its convention through the values that leave no
choice.

**Decision.**
- A clone reads each DATE/DATETIME column once before writing it and counts the
  distinct numeric `d/m/y` values that prove an order (a part above 12, the other
  a valid month): `DMY` proofs and `MDY` proofs (`normalizers.date.column_date_evidence`).
- The column states an order only when every proof agrees and there are enough
  of them that a column mixing both orders evenly would show this little
  disagreement less than 5% of the time (`2 * 0.5**k < 0.05`, so at least 6
  proofs: the same 0.05 as ADR-019's delta). Fewer proofs, or any proof of the
  other order, states nothing and the values stay AMBIGUOUS.
- The order reaches the normalizer explicitly, as `context.column_date_order`
  (order, proofs), never inferred inside it. A stated country or locale order
  comes first; when the column's own values contradict it, neither is used and
  the values stay AMBIGUOUS (a stated `DMY` would otherwise misread a column
  that proves `MDY`).
- Every value read this way records the evidence in `structured.column_evidence`
  (`order`, `proving_values`, `contradicting_values` = 0), and the job keeps the
  counts per column under `column_evidence`, computed once, so a resume reads
  the same order.
- A person's verdict (ADR-018) wins: the column order is derived from the data,
  not part of the question, so it is left out of the verdict key, and a context
  without one hashes exactly as before the field existed (no stored verdict or
  cache key moves).
- On by default (user decision 2026-10-18, after REPORT §11.13 showed Raha's year-first
  corruptions are written as dates, exactly as with a stated `country=US`): no new guess is made. The order is proven by the column, and a
  column that proves nothing behaves exactly as before.

**Limits.** The model is the normalizer's own: the year is the last part. Proofs
are counted over distinct values, not cells, so one repeated value is one proof.
The pre-pass is one extra read of the date columns of a table.

## Amendment 2026-11-10: a component the parser filled from its base date is never stated (D24)

**Context.** Non-strict `dateparser` fills every component the text lacks from its base date,
which was the clock. Under D/M/Y it reads `11/30 10:30 p.m.` as day 11 of 2030. In November the
filled month matched the `11`, so the value read as November 2030 (AMBIGUOUS). In any other month
it stayed INVALID (`test_a_time_is_no_day_or_month`, failing since 2026-11-01). The answer
depended on the date of the run.

**Decision.** The partial path (`normalizers.date._parse_partial`) parses each candidate at two
fixed base dates that differ in month and day (`_PARTIAL_BASES`). A month or day that moves
between the two came from the base, and `_stated_precision` never lets it claim a number or a
month name. The strict path fills nothing (`STRICT_PARSING`), so it is unchanged. Neither path
reads the clock now. Orchestrator 2026-11-09, under the owner's "All but 4 limits": "Q1: a".

**Limits.** A value whose first reading has month or day equal to the first base's is parsed a
second time. Measured on 600 sampled distinct movie dates (`bm_round2_movies`, seed 24), with
the clock pinned to April and November, with no country and with `NO`: 0 results changed, and
the time was 9.4-11.0 s against 9.5-10.7 s before.
