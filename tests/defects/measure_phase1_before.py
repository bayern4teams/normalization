"""BEFORE numbers for Phase 1 on the current code (plan 8 Phase 0 step 4).

Run:  uv run python tests/defects/measure_phase1_before.py [--rev <sha>] [--check]

Not collected by pytest (no test_ prefix). Prints, per fixture group, the
scorer's outcome counters and the item-specific measurements.

BEFORE mode reads source *greps* from the commit HEAD, so a half-built working
tree cannot contaminate the baseline; the engine itself always runs from the
working tree (run it before any normalizer edit lands, or on a clean checkout).
With --check the greps read the working tree and the script exits non-zero
unless the Phase-1 bars hold: use it as the AFTER gate. On today's code it must
fail, which is the negative control.
"""

from __future__ import annotations

import pkgutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
import pycountry  # noqa: E402
import stdnum  # noqa: E402
from normapi.scaffold_profile import SCAFFOLD_PROFILE  # noqa: E402
from normcore.context import NormalizationContext  # noqa: E402
from normcore.enums import FieldSemanticType  # noqa: E402
from normcore.models import NormalizedValue  # noqa: E402

# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
from defects import fixtures_phase1 as fx  # noqa: E402
from defects.scorer import Case, _dispatcher, real_engine, score  # noqa: E402

AFTER = "--check" in sys.argv
# The commit the greps read in BEFORE mode: `--rev <sha>` (default HEAD). The recorded
# BEFORE numbers use e6fa923, the last commit before any D1 code landed.
REV = sys.argv[sys.argv.index("--rev") + 1] if "--rev" in sys.argv else "HEAD"
failures: list[str] = []


def bar(ok: bool, text: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    if not ok:
        failures.append(text)


def git_grep(pattern: str, *paths: str) -> list[tuple[str, int]]:
    """(file, match count). HEAD in BEFORE mode, the working tree with --check."""
    cmd = ["git", "grep", "-c", "-i", "-E"]
    cmd += ["--untracked", pattern] if AFTER else [pattern, REV]
    out = subprocess.run(
        [*cmd, "--", *paths], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout
    rows = [line.rsplit(":", 1) for line in out.splitlines() if line]
    return [(f.removeprefix(f"{REV}:"), int(n)) for f, n in rows]


def run(case: Case) -> NormalizedValue:
    sem = FieldSemanticType[case.semantic_type]
    ctx = NormalizationContext(field_name="f", semantic_type=sem, **dict(case.context))  # type: ignore[arg-type]
    return _dispatcher().normalize(case.input, sem, ctx, SCAFFOLD_PROFILE)


def show(title: str, cases: tuple[Case, ...]) -> Counter[str]:
    got = score(cases, real_engine)
    print(f"{title:28s} n={len(cases):2d}  {dict(sorted(got.items()))}")
    return got


# ---------------------------------------------------------------- D1
print("== D1  abstention path (planted ground truth, real dispatcher)")
amb = {
    "phone": show("D1 phone ambiguous", fx.D1_PHONE_AMBIGUOUS),
    "date": show("D1 date ambiguous", fx.D1_DATE_AMBIGUOUS),
    "money": show("D1 money ambiguous", fx.D1_MONEY_AMBIGUOUS),
}
ctl = {
    "phone": show("D1 phone controls (clean)", fx.D1_PHONE_CLEAN),
    "date": show("D1 date controls (clean)", fx.D1_DATE_CLEAN),
    "money": show("D1 money controls (clean)", fx.D1_MONEY_CLEAN),
}
for c in fx.D1_ALL:
    if c.expected == "clean" and real_engine(c)[0].value in {"AMBIGUOUS", "INVALID"}:
        print(f"    control not clean today: {c.id} {c.input!r} -> {real_engine(c)[0].value}")
prec = show("precision controls (dates)", fx.D1_DATE_PRECISION)
for c in fx.D1_DATE_PRECISION:
    status, value = real_engine(c)
    if value != c.expected_value:
        print(f"    precision today: {c.input!r} -> {value!r} (expected {c.expected_value!r})")
planted = len(fx.D1_AMBIGUOUS_ONLY)
abstained = sum(g["correct-abstain"] for g in amb.values())
queue_hits = git_grep(r"adjudication|review[_ -]queue", "packages")
print(f"planted ambiguous values: {planted}; the engine abstains on {abstained} (correct-abstain)")
print(f"files in packages/ naming an adjudication/review queue: {len(queue_hits)} {queue_hits}")
reach_queue = "n/a (a queue exists)" if queue_hits else 0
print(f"planted ambiguous values that reach any queue today: {reach_queue} of {planted}")
bar(
    all(g["wrong-confident"] == 0 for g in (*amb.values(), *ctl.values())),
    "engine never guesses on D1 fixtures (wrong-confident == 0)",
)
over = sum(g["over-abstain"] for g in ctl.values())
print(f"  [INFO] over-abstain on controls: {over} (05/05/2024 has one reading; not a report item)")
print(f"  [INFO] precision controls wrong-confident: {prec['wrong-confident']} (not a bar)")
bar(bool(queue_hits), "an adjudication queue exists in packages/ (D1)")

# ---------------------------------------------------------------- D7
print("\n== D7  stdnum registry / tri-state")
d7 = {
    "valid": show("D7 valid (6 non-registry)", fx.D7_VALID),
    "invalid": show("D7 invalid twin", fx.D7_INVALID),
    "unverifiable": show("D7 unlisted / no country", fx.D7_UNVERIFIABLE),
}
iso = {c.alpha_2 for c in pycountry.countries}
codes = sorted(
    m.name.rstrip("_").upper()
    for m in pkgutil.iter_modules(stdnum.__path__)
    if m.ispkg and m.name.rstrip("_").upper() in iso
)
reach = [
    cc
    for cc in codes
    if run(Case("p", "TAX_ID", "0", "invalid", context={"country": cc})).structured.get(
        "identifier_type"
    )
]
print(f"stdnum country packages: {len(codes)}; checkable for TAX_ID today: {len(reach)} {reach}")
r = run(fx.D7_UNVERIFIABLE[0])
print(
    f"unlisted country {fx.UNLISTED_COUNTRY}: status={r.normalization_status.value} "
    f"validation_status={r.validation_status!r}  (should claim nothing: UNKNOWN / unverifiable)"
)
fixture_countries = set(fx.TAX_NUMBERS)
bar(
    fixture_countries <= set(reach) and fx.UNLISTED_COUNTRY not in reach and len(reach) > 4,
    f"the {len(fixture_countries)} fixture countries are reachable; the unlisted one is not",
)
bar(d7["invalid"]["correct"] == len(fx.D7_INVALID), "one-digit-changed twins are INVALID in all 6")
bar(
    d7["unverifiable"]["correct-abstain"] == len(fx.D7_UNVERIFIABLE), "unlisted/no country abstains"
)
bar(d7["valid"]["correct"] == len(fx.D7_VALID), "valid numbers stay clean")

# ---------------------------------------------------------------- D8
print("\n== D8  TAX_ID vs CODE on one string")
d8 = show("D8 pairs", fx.D8_ALL)
identical = 0
differs_exactly_when_invalid = True
for tax, code in fx.D8_PAIRS:
    t, c = run(tax), run(code)
    same = t.validation_status == c.validation_status
    identical += same
    differs_exactly_when_invalid &= (not same) == (tax.expected == "invalid")
    print(
        f"  {tax.input!r:12} {tax.context['country']}: TAX_ID {t.validation_status}/"
        f"{t.normalization_status.value}  CODE {c.validation_status}/{c.normalization_status.value}"
        f"  check_digit_valid(CODE)={c.structured.get('check_digit_valid')!r}  identical={same}"
    )
print(f"pairs with identical validation_status today: {identical}/{len(fx.D8_PAIRS)}")
bar(differs_exactly_when_invalid, "validation_status differs exactly where a check digit is wrong")
bar(
    all(run(c).structured.get("check_digit_valid") is None for _, c in fx.D8_PAIRS),
    "CODE never reports a check-digit verdict, even with a country in context",
)
bar(d8["wrong-confident"] == 0 and d8["over-abstain"] == 0, "D8 scorer: no wrong-confident")

# ---------------------------------------------------------------- D9
print("\n== D9  registrable domain / public suffix (URL normalizer structured output)")
answered = 0
naive_right = []
for uc in fx.D9_CASES:
    s = run(Case(uc.id, "URL", uc.url, "clean")).structured
    keys = ("registrable_domain", "public_suffix", "is_private_suffix")
    ok = (
        all(k in s for k in keys)
        and s["registrable_domain"] in fx.registrable_answers(uc)
        and s["public_suffix"] == uc.public_suffix
        and s["is_private_suffix"] == uc.is_private_suffix
    )
    answered += ok
    if fx.naive_registrable_domain(str(s["host"])) in fx.registrable_answers(uc):
        naive_right.append(uc.id)
print(f"cases answered by today's structured output: {answered}/{len(fx.D9_CASES)}")
print(f"cases a last-two-labels rule over structured['host'] gets right by accident: {naive_right}")
bar(answered == len(fx.D9_CASES), "structured holds the correct PSL triple for all D9 cases")

# ---------------------------------------------------------------- D12
print("\n== D12  NEEDS_REVIEW")
hits = git_grep("NEEDS_REVIEW", "packages", "ui", "docs")
src = [(p, n) for p, n in hits if p.startswith("packages/") and "/src/" in p]
print(f"files mentioning NEEDS_REVIEW in packages/ui/docs: {len(hits)}")
print(f"  of which packages src: {src}")
producers = [
    p for p, _ in src if not p.endswith(("enums.py", "dispatch.py", "normalizers/date.py"))
]
print(f"  producers outside enums.py / dispatch.py / the date.py docstring: {producers}")
bar(
    not src or bool(producers), "NEEDS_REVIEW is gone everywhere, or has a producer in packages src"
)

print(f"\n{len(failures)} bar(s) unmet")
if AFTER:
    sys.exit(1 if failures else 0)
