"""BEFORE numbers for D10, D11, D5, D4 on the current code (P0-B).

Run: `uv run python tests/defects/measure_phase23_before.py`

Not collected by pytest (no test_ prefix). Prints counts, not rates. Re-run the
same script after each item lands; the AFTER numbers are the same lines.
"""

from __future__ import annotations

import importlib.util
from collections import Counter

import fixtures_phase23 as fx  # sibling module: the script dir is on sys.path
from normanalysis.type_detection import suggest_semantic_type
from normapi.app import build_dispatcher
from normapi.clone_executor import _apply_value
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as F

from normio import storage_types

DISPATCHER = build_dispatcher(env_id="phase23-before")


def norm(text: str | None, sem: F, **ctx: str):  # type: ignore[no-untyped-def]
    context = NormalizationContext(field_name="f", semantic_type=sem, **ctx)  # type: ignore[arg-type]
    return DISPATCHER.normalize(text, sem, context, SCAFFOLD_PROFILE)


def head(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------- D10
def d10() -> None:
    head("D10 phone extensions")
    cases = fx.build_phone_extension_cases()
    one_comparison = base_eq_ext = ext45_eq_ext46 = search_has_ext = rfc_key = ext_kept = 0
    spellings_total = 0
    parsed_ext = Counter()
    for c in cases:
        res = {label: norm(text, F.PHONE) for label, text in c.spellings.items()}
        base = norm(c.base_international, F.PHONE)
        other = norm(c.other_extension, F.PHONE)
        spellings_total += len(res)
        for label, r in res.items():
            parsed_ext[(label, r.structured.get("extension"))] += 1
            ext_kept += r.structured.get("extension") == fx.EXTENSION
            rfc_key += "rfc3966" in r.structured
        if len({r.comparison for r in res.values()}) == 1:
            one_comparison += 1
        first = next(iter(res.values()))
        base_eq_ext += base.comparison == first.comparison
        ext45_eq_ext46 += other.comparison == first.comparison
        search_has_ext += any(r.search != c.base_e164 for r in res.values())
    n = len(cases)
    print(f"regions planted: {n}; extension spellings per region: {len(fx.EXTENSION_SPELLINGS)}")
    print(f"regions where all 4 spellings share ONE comparison: {one_comparison}/{n}")
    print(f"regions where base number == base+x45 in comparison (DEFECT): {base_eq_ext}/{n}")
    print(f"regions where x45 == x46 in comparison (DEFECT): {ext45_eq_ext46}/{n}")
    print(f"spellings parsed to extension '45' in structured: {ext_kept}/{spellings_total}")
    print(f"spellings carrying structured['rfc3966']: {rfc_key}/{spellings_total}")
    print(f"regions where search differs from the extension-free E.164: {search_has_ext}/{n}")
    print("per-spelling parsed extension:", dict(parsed_ext))
    amb = norm(fx.PHONE_NO_REGION_WITH_EXTENSION, F.PHONE)
    inv = norm(fx.PHONE_INVALID_WITH_EXTENSION, F.PHONE)
    print(f"never-guess no region + ext -> {amb.normalization_status.value}")
    print(f"invalid country code + ext  -> {inv.normalization_status.value}")
    nat = [norm(c.national_with_extension, F.PHONE, country=c.region) for c in cases]
    print(
        f"national+ext with country context parsed to ext 45: "
        f"{sum(r.structured.get('extension') == fx.EXTENSION for r in nat)}/{n}"
    )
    # Idempotency baseline: re-normalizing the emitted comparison.
    idem = sum(
        norm(r.comparison, F.PHONE).comparison == r.comparison
        for r in (norm(c.spellings["x"], F.PHONE) for c in cases)
    )
    print(f"re-normalizing emitted comparison is stable: {idem}/{n}")


# ---------------------------------------------------------------- D11
def keys_of(text: str) -> dict[str, str] | None:
    r = norm(text, F.FAMILY_NAME)
    ph = r.structured.get("phonetic")
    return dict(ph) if isinstance(ph, dict) else None


def shared(a: str, b: str, which: tuple[str, ...]) -> bool:
    ka, kb = keys_of(a), keys_of(b)
    return bool(ka and kb and any(k in ka and k in kb and ka[k] == kb[k] for k in which))


def d11() -> None:
    head("D11 phonetics")
    groups = fx.build_name_groups()
    for label, gen in (("human-asserted spellings", False), ("incl. ICU-generated", True)):
        pairs = [(a.text, b.text) for g in groups for a, b in g.pairs(generated=gen)]
        soundex = sum(shared(a, b, ("soundex",)) for a, b in pairs)
        anyk = sum(shared(a, b, fx.PHONETIC_KEYS) for a, b in pairs)
        print(
            f"same-name pairs [{label}]: {len(pairs)}; share Soundex: {soundex}; "
            f"share >=1 of 4 keys: {anyk}"
        )
    cross = [
        (a.text, b.text)
        for g in groups
        for a, b in g.pairs(generated=False)
        if a.script != b.script
    ]
    print(
        f"  cross-script human pairs: {len(cross)}; "
        f"Soundex {sum(shared(a, b, ('soundex',)) for a, b in cross)}; "
        f"any key {sum(shared(a, b, fx.PHONETIC_KEYS) for a, b in cross)}"
    )
    for g in groups:
        for a, b in g.pairs(generated=False):
            if a.script != b.script and not shared(a.text, b.text, fx.PHONETIC_KEYS):
                print(f"    no shared key today: {g.group}: {a.text!r} / {b.text!r}")
    diff = fx.DIFFERENT_NAME_PAIRS
    print(
        f"different-name pairs: {len(diff)}; collide on Soundex: "
        f"{sum(shared(a, b, ('soundex',)) for a, b in diff)}; collide on any key: "
        f"{sum(shared(a, b, fx.PHONETIC_KEYS) for a, b in diff)}"
    )
    inputs = fx.non_latin_inputs()
    carrying = Counter()
    n_any = 0
    for t in inputs:
        k = keys_of(t) or {}
        n_any += bool(k)
        carrying.update(name for name, v in k.items() if v)
    print(f"non-Latin inputs: {len(inputs)}; carrying any key: {n_any}; per key: {dict(carrying)}")
    cjk = sum(bool(keys_of(t)) for t in fx.CJK_NAMES)
    print(f"CJK/Hangul names carrying keys today: {cjk}/{len(fx.CJK_NAMES)}")
    na = sum(
        (norm(t, F.FAMILY_NAME).structured.get("phonetic_status") == "not_applicable")
        for t in inputs
    )
    print(f"non-Latin inputs already marked phonetic_status=not_applicable: {na}/{len(inputs)}")
    print(
        "Latin diacritic names carry keys today (no expectation planted):",
        {t: bool(keys_of(t)) for t in fx.LATIN_DIACRITIC_NAMES},
    )
    drift = [t for t, old in fx.LATIN_OLD_KEYS.items() if keys_of(t) != old]
    print(f"Latin plain names whose keys differ from LATIN_OLD_KEYS: {drift or 'none'}")


# ---------------------------------------------------------------- D5
def d5() -> None:
    head("D5 typed destination: coerce on adversarial strings")
    typed = [t.name for t in F if storage_types.is_typed(t.name)]
    untyped = [t.name for t in F if not storage_types.is_typed(t.name)]
    print(f"natively typed types (read from storage_types): {typed}")
    for engine in ("postgres", "clickhouse"):
        for t in typed:
            ddl = storage_types.sql_type(t, engine)
            outcomes: Counter[str] = Counter()
            bad = []
            for label, text in fx.ADVERSARIAL_STRINGS:
                try:
                    value, err = storage_types.coerce(t, text)
                except Exception as exc:
                    outcomes["raises"] += 1
                    bad.append((label, f"RAISES {type(exc).__name__}"))
                    continue
                if err is not None:
                    outcomes["error"] += 1
                elif value is None:
                    outcomes["null-no-error"] += 1
                elif fx.engine_accepts(ddl or "", value):
                    outcomes["typed-fits"] += 1
                else:
                    outcomes["typed-OVERFLOW"] += 1
                    bad.append((label, "cast succeeded but the column cannot hold it"))
            print(f"  {engine:10s} {t:8s} {ddl:14s} {dict(outcomes)}")
            for label, why in bad:
                print(f"      {label}: {why}")
    d5_end_to_end(typed, untyped)


def d5_end_to_end(typed: list[str], untyped: list[str]) -> None:
    # Real path: dispatcher result -> _apply_value (the clone executor's own cast gate).
    print("  end-to-end (dispatcher -> _apply_value), cell outcomes per typed type:")
    for t in typed:
        sem = F[t]
        cells: Counter[str] = Counter()
        for label, text in fx.ADVERSARIAL_STRINGS:
            try:
                res = norm(text, sem)
                row = {"c": text}
                errs = _apply_value(
                    row, res, column="c", typed_as=t, companion=None, code_column=None
                )
                v = row["c"]
                cells["error-row" if errs else ("NULL" if v is None else "typed-value")] += 1
                for engine in ("postgres", "clickhouse"):
                    ddl = storage_types.sql_type(t, engine) or ""
                    if v is not None and not errs and not fx.engine_accepts(ddl, v):
                        cells[f"OVERFLOW-REACHES-INSERT-{engine}"] += 1
                        print(f"      {t} {label}: {engine} {ddl} cannot hold the emitted value")
                if isinstance(v, str):
                    cells["RAW-STRING-IN-TYPED-CELL"] += 1
                    print(f"      {t} {label}: raw string reached the typed cell: {v!r}")
            except Exception as exc:
                cells[f"raises {type(exc).__name__}"] += 1
        print(f"    {t:8s} {dict(cells)}")
    nul_through = [t for t in untyped if storage_types.coerce(t, "\x00")[0] == "\x00"]
    print(
        f"  untyped types where coerce passes '\\x00' through unchanged: {len(nul_through)}/"
        f"{len(untyped)} (Postgres TEXT rejects NUL: out of D5's typed scope, noted)"
    )
    kept = [
        t
        for t in ("DATE", "DATETIME")
        if all(storage_types.coerce(t, p) == (p, None) for p in fx.PARTIAL_DATES)
        and storage_types.sql_type(t, "postgres") is None
    ]
    print(f"  DATE/DATETIME stay TEXT and keep all partial dates unchanged: {kept}")


# ---------------------------------------------------------------- D4
def d4() -> None:
    head("D4 disguised missing data")
    mod = importlib.util.find_spec("normanalysis.disguised_missing")
    print(f"normanalysis.disguised_missing exists: {mod is not None}")
    for col in fx.build_d4_columns():
        sem = F.COUNTRY if col.name.startswith("country") else F.DATE
        distinct = Counter(col.values)
        kinds: Counter[str] = Counter()
        kind_by_value: dict[str, str] = {}
        flagged_errors: Counter[str] = Counter()
        for v, n in distinct.items():
            r = norm(v, sem)
            if r.original_kind is not None:
                kinds[r.original_kind.value] += n
                kind_by_value[v] = r.original_kind.value
                row = {"c": v}
                errs = _apply_value(
                    row, r, column="c", typed_as=None, companion=None, code_column=None
                )
                flagged_errors[v] = len(errs)
        print(
            f"- {col.name}: {len(col.values)} rows, {len(distinct)} distinct; planted truth: "
            f"{col.expected_reported or 'report nothing'}"
        )
        print(f"    cell-level missing classification today (row counts by kind): {dict(kinds)}")
        print(f"    values classified missing: {kind_by_value}")
        print(
            f"    of those, values that emit an error row today: "
            f"{ {k: v for k, v in flagged_errors.items() if v} }"
        )
        wrongly = {
            v: n
            for v, n in distinct.items()
            if v in kind_by_value and v not in col.expected_reported
        }
        print(f"    classified missing but planted truth says NOT a sentinel: {wrongly}")
        # Column level (what the report calls the only level today).
        name = "country" if sem is F.COUNTRY else "birth_date"
        top = suggest_semantic_type(
            name, sample_values=col.values[:200], registry=DISPATCHER.registry
        )[0]
        print(f"    column-level suggestion: {top.semantic_type.value} @ {top.confidence:.2f}")


if __name__ == "__main__":
    d10()
    d11()
    d5()
    d4()
