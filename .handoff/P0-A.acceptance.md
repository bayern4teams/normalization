# P0-A acceptance (derive mode): Phase 1 fixtures, shared scorer, BEFORE numbers

Files: `tests/defects/{__init__,scorer,fixtures_phase1,test_scorer,measure_phase1_before}.py`.
Import as `from defects.scorer import Case, score, real_engine` (pytest puts `tests/` on the path;
the measure script does the same by hand). Derived from the report's Evidence/Fix text and plan 9, not from any worker code.

## What each fixture group checks (values from authoritative sources, built at import)
| group | n | truth source | checks |
|---|---|---|---|
| D1 phone ambiguous | 8 | libphonenumber example numbers, candidates = distinct E.164 over every region where `is_valid_number` | no region, no "+" -> abstain, never one E.164 |
| D1 date ambiguous | 4 | calendar arithmetic (both readings) | `01/02/2024` etc. -> abstain, candidates {DMY, MDY} ISO |
| D1 money ambiguous | 4 | CLDR via Babel (`parse_decimal` en vs de) | `1,234` -> abstain, candidates {1234, 1.234} |
| D1 controls (clean) | 9+5+4 | libphonenumber, Babel `format_decimal`, `date` | with region/locale/unambiguous form the engine must emit; stops "abstain on everything" passing |
| D1 precision controls | 3 | ISO precision rule (CLAUDE.md) | `2024-03`, `1990`, `03/2024` keep month/year, no invented day |
| D7 valid / invalid twin | 6 + 6 | stdnum `calc_check_digit` + `is_valid`, PT GR CL CO TR AR (none in US/GB/DE/FR), twin = last char changed, asserted invalid | check digit applies for any stdnum country |
| D7 unverifiable | 2 | first ISO country with no stdnum package (AE today), and TAX_ID with no country | answer is abstain / UNKNOWN, never VALID and never INVALID |
| D8 pairs | 3 pairs | stdnum luhn (FR SIREN, a registry country), PT NIF valid and bad-check | same string as TAX_ID+country vs CODE: statuses differ exactly where the check digit is wrong; CODE has no check-digit verdict |
| D9 URL table | 10 | PSL rules, verified against publicsuffix.org 2026-10-05 (`co.uk`,`uk`,`jp` ICANN; `github.io` PRIVATE; `notatld` unlisted) | `a.co.uk`, `b.a.co.uk`, `x.github.io`, `例え.jp` (and A-label form), IPv4, IPv6, `localhost`, `foo.notatld`; plus `naive_registrable_domain` (last two labels) which the table exposes (test_scorer asserts it) |
| D12 | grep | n/a | bar: NEEDS_REVIEW gone from packages/ui/docs, or has a producer under packages src |

Scorer outcomes: correct, correct-abstain, wrong-confident, over-abstain, wrong-status. `real_engine` returns the `comparison` view and
maps `validation_status` UNKNOWN/AMBIGUOUS on a clean status to AMBIGUOUS (the engine signature has no validation channel; this is how D7 "unverifiable" is scored).
`test_scorer.py` (29 tests, all pass): oracle all correct; guesser named wrong-confident; abstainer named over-abstain; every NormalizationStatus classifies; fixtures checked against stdnum/CLDR.

## BEFORE numbers (engine from working tree, greps at e6fa923 = last commit before D1 code; `--rev e6fa923`)
- D1: 16/16 planted ambiguous values abstain (correct-abstain) and 0/16 reach any queue (grep for adjudication/review queue in packages/: 0 files). wrong-confident 0.
- D7: reachable countries 4 of 85 stdnum country packages (DE FR GB US). valid 6/6 correct; invalid twins 0/6 caught (6 wrong-confident); unlisted + no-country 0/2 abstain (AE comes back NORMALIZED/VALID).
- D8: identical validation_status for TAX_ID vs CODE in 2 of 3 pairs (both PT pairs); FR pair already differs.
- D9: 0/10 cases answered (no registrable_domain/public_suffix/is_private_suffix key).
- D12: NEEDS_REVIEW in 3 packages src files (enums.py, dispatch.py severity tuple, date.py docstring), 0 producers.
- AFTER gate: `uv run python tests/defects/measure_phase1_before.py --check` exits 1 today (8 bars unmet), 0 only when D1 queue, D7, D8, D9, D12 bars all hold.

## Report examples that ALREADY pass today (so a green result there proves nothing)
- Abstention itself: phone, date, money all return AMBIGUOUS today (D1 is about the exit path, not the refusal).
- D8: a check-digit-invalid number as TAX_ID vs CODE differs already, for the four registry countries (FR pair).
- D8: `check_digit_valid` on CODE is None today (key present, no verdict).
- D7: valid numbers for non-registry countries come back NORMALIZED (6/6 "correct") because everything unchecked is clean; only the invalid twin and unverifiable cases discriminate.
- D9: `localhost`, IPv6, `a.uk`, both `.jp` IDN forms are matched by a naive last-two-labels rule over `structured["host"]` by accident; only `a.co.uk`, `b.a.co.uk`, `x.github.io`, IPv4, `foo.notatld` expose it.

## Findings outside the report (not bars)
- `05/05/2024` abstains today although both readings are the same date (over-abstain).
- `03/2024` normalizes to `2024-03-03`: a day is invented from a month-year string (wrong-confident vs expected `2024-03`).

## Section 2.4 checks for the verifier
Grep over added lines (run by the attacker): `git diff e6fa923 -- packages tests | grep -E '^\+' | grep -vE '^\+\+\+' | grep -nE '\{("[A-Z]{2}",? *){3,}|"(co|com|org|ac|gov)\.[a-z]{2}"|phonetic|^\+[^#]*[<>]=? *0\.[0-9]'`
and confirm every hit is test code or carries a source/`ponytail:` note. Question per item: would stdnum / PSL / CLDR / libphonenumber produce this value at run time?
Never-guess cases: (a) D1 ambiguous groups must stay `correct-abstain` or resolve only via a stored verdict, wrong-confident 0; (b) a verdict for one value must not answer another value or another country; (c) D7 unlisted country and no-country must be unverifiable, not VALID/INVALID; (d) precision controls: month/year inputs keep their precision; (e) D9 IP/localhost/unlisted TLD give None, not the last two labels.

## Could not do
- Several-candidate-modules case for D7 (needs the worker's term list; not derivable from the report). Countries with several tax-like modules were left out of the fixture.
- libphonenumber, CLDR and stdnum are the installed versions, not live; PSL was checked online once, no PSL data is vendored or fetched by the fixtures.
- No D1 end-to-end/queue behavior (needs the lead's store; unverified-live per plan 11). The earlier-written fixtures do not exercise `clone_executor`.
- Another verifier's `tests/defects/fixtures_phase23.py` exists; I ran `ruff check --fix` once on the whole directory before noticing it and it reported 1 autofix whose file I cannot identify.
