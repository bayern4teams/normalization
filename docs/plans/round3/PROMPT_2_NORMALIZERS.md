# Prompt 2 — normalizers: country, currency, money, language

Give this text to a new session in `/home/bayern/Projects/normalization`.

---

You build items D27, D28, D29, D30, D20 and D21 of `docs/improvement-report.md`, Part 1, round 3,
in that order.

Read first, in this order:

1. `AGENTS.md`, all of it. Its §4 rules "Never guess on ambiguous data" and "Changes must be
   general" decide every item here.
2. `docs/plans/round3/README.md`, "Rules every prompt adds to AGENTS.md". Follow every rule.
3. `docs/improvement-report.md`: §0, the D16-D24 table (D20, D21) and the D25-D32 table, with
   the owner's answers quoted in each row.
4. `docs/research/resources/_raw-country-currency-findings.md`.
5. ADR-010 (country and language), ADR-011 (currency), ADR-018 (what AMBIGUOUS means).

Per item:

- **D27.** Withdrawn codes with several successors become AMBIGUOUS with CLDR's successors as
  readings; never pick one. `CS` gets `RS`, `ME` and the historic entity `CSHH` (owner "b3b. a").
  No hand-made successor list.
- **D28.** CLDR `alt="short"` names; a leading "The" stripped only when the rest is an exact,
  unambiguous name; `Congo` and `Korea` AMBIGUOUS with both readings. No GeoNames table.
- **D29.** `XYZ`, `XTS`, `XXX`: INVALID with an error message that says how to fix it; a clone
  writes one error row each. Prove the error row with a clone on the benchmark machine.
- **D30.** `$5` with no country: AMBIGUOUS, the amount kept, the currencies that use `$` as
  readings (from CLDR data, never a hand list). Amend ADR-011 in the same commit.
- **D20.** Lower-case `mon` stays AMBIGUOUS; `_` reads as `-` only inside a valid locale tag.
- **D21.** A phone in international form gives the row its country; a national-format phone
  does not.

Every change to which values resolve changes `context_hash` or verdict keys only where the
report says so. Check with the property tests under `tests/property/` that nothing else moved.

Stop and ask the owner when a reading list would need a hand-written table, or when a change
would turn an AMBIGUOUS or INVALID value into a confident one that the report does not name.
