"""Independent acceptance checks for D11 (phonetics that fit the data).

Derived from docs/archive/plans/DEFECTS_IMPLEMENTATION_PLAN.md section 9 D11 *Accept*,
section 2.4, and
docs/improvement-report.md D11 + Part 2 "Names, multi-script", not from the implementation.

Target contract (field names are part of the spec; see .handoff/D11.acceptance.md in git history):

* `structured["phonetic"]` (dict, already exists) holds the four legacy keys `soundex`, `nysiis`,
  `metaphone`, `match_rating_codex` ONLY for Latin-script input, and may additionally hold the
  language-aware keys `double_metaphone` and `beider_morse`. A language-aware value is a non-empty
  `str` or `list[str]` of alternative codes (a `|` or whitespace inside a string also separates
  alternatives); two names share a key when the same-named key has one code in common.
* `structured["phonetic_status"] == "not_applicable"` and `structured["script"]` (an ISO 15924 long
  name or 4-letter code, case-insensitive) on every non-Latin-script input: no legacy key, ever.
* CJK (Han, Hangul), Devanagari and Thai: no phonetic key of any kind (polyphonic readings).
* Latin input: every legacy key and every other pre-existing output is byte-identical to the
  snapshot captured BEFORE D11 (tests/defects/d11_latin_snapshot.json).

Phase 0 baseline (tests/defects/PHASE0 report section 4) was measured on a different pair set; the
baseline for THIS pair set is recomputed here from jellyfish + anyascii directly (the old algorithm,
independent of name.py) and pinned in `_PINNED_BASELINE`. Counts are reported, never rates.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import anyascii
import jellyfish
import pytest
from normalizers.name import NameNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as F
from normcore.enums import NormalizationStatus
from normdict.loader import DictionaryLoader
from normexec.env_fingerprint import FINGERPRINTED_PACKAGES

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ holds the `defects` package
from defects import fixtures_d11 as fx

ROOT = Path(__file__).parents[2]
SNAPSHOT = ROOT / "tests" / "defects" / "d11_latin_snapshot.json"
NORMALIZERS_SRC = ROOT / "packages" / "normalizers" / "src" / "normalizers"
D11_FILES = (NORMALIZERS_SRC / "name.py", NORMALIZERS_SRC / "_bmpm.py")

# Old algorithm over THIS pair set, computed once before D11 (jellyfish 1.2.1, anyascii 0.3.3).
_PINNED_BASELINE = {"pairs": 170, "soundex": 119, "any_legacy": 124, "cross_pairs": 83, "cross": 56}

pytestmark = pytest.mark.unit

_NORMALIZER = NameNormalizer(DictionaryLoader(ROOT / "data" / "dictionaries"))


def norm(text: str, sem: F = F.FAMILY_NAME) -> Any:
    return _NORMALIZER.normalize(text, NormalizationContext(field_name="f", semantic_type=sem))


def phonetic(text: str, sem: F = F.FAMILY_NAME) -> dict[str, Any]:
    ph = norm(text, sem).structured.get("phonetic")
    return dict(ph) if isinstance(ph, dict) else {}


def _alts(value: object) -> set[str]:
    items = [value] if isinstance(value, str) else list(value) if isinstance(value, list) else []
    assert all(isinstance(i, str) for i in items), f"codes must be strings, got {value!r}"
    return {c for i in items for c in re.split(r"[|\s]+", i) if c}


def codes(text: str) -> dict[str, set[str]]:
    return {k: _alts(v) for k, v in phonetic(text).items() if k in (*fx.LEGACY_KEYS, *fx.NEW_KEYS)}


def shares(a: str, b: str) -> bool:
    ca, cb = codes(a), codes(b)
    return any(ca[k] & cb[k] for k in ca.keys() & cb.keys())


def legacy_old(text: str) -> dict[str, set[str]]:
    """The pre-D11 algorithm, re-stated independently of name.py."""
    letters = "".join(c for c in anyascii.anyascii(text) if c.isalpha())
    if not letters:
        return {}
    return {
        "soundex": {jellyfish.soundex(letters)},
        "nysiis": {jellyfish.nysiis(letters)},
        "metaphone": {jellyfish.metaphone(letters)},
        "match_rating_codex": {jellyfish.match_rating_codex(letters)},
    }


def old_shares(a: str, b: str, keys: tuple[str, ...] = fx.LEGACY_KEYS) -> bool:
    la, lb = legacy_old(a), legacy_old(b)
    return any(la[k] & lb[k] for k in keys if k in la and k in lb)


def _script_ok(structured: dict[str, Any], accepted: tuple[str, ...]) -> bool:
    return str(structured.get("script", "")).lower() in accepted


PAIRS = fx.same_name_pairs()
CYRILLIC_ARABIC = sorted(
    {p.a for p in PAIRS if p.a_script != "Latin"} | {p.b for p in PAIRS if p.b_script != "Latin"}
)
LATIN_SPELLINGS = sorted(
    {p.a for p in PAIRS if p.a_script == "Latin"} | {p.b for p in PAIRS if p.b_script == "Latin"}
)
SCRIPT_OF = {
    **{t: fx.SCRIPT_LABELS["Cyrillic"] for t in CYRILLIC_ARABIC if re.search("[Ѐ-ӿ]", t)},
    **{t: fx.SCRIPT_LABELS["Arabic"] for t in CYRILLIC_ARABIC if re.search("[؀-ۿ]", t)},
    **dict.fromkeys(fx.HAN_NAMES, fx.SCRIPT_LABELS["Han"]),
    **dict.fromkeys(fx.HANGUL_NAMES, fx.SCRIPT_LABELS["Hangul"]),
    **dict(fx.OTHER_NON_LATIN),
}
NO_KEY_AT_ALL = (*fx.HAN_NAMES, *fx.HANGUL_NAMES, "राजेश", "สมชาย")
SEMS = (F.FAMILY_NAME, F.GIVEN_NAME)


# ---------------------------------------------------------------------------
# (a) no Anglo-centric key on non-Latin input; status + script instead
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sem", SEMS)
@pytest.mark.parametrize("text", sorted(SCRIPT_OF))
def test_non_latin_never_carries_legacy_keys_and_is_marked(text: str, sem: F) -> None:
    r = norm(text, sem)
    leaked = set(phonetic(text, sem)) & set(fx.LEGACY_KEYS)
    assert not leaked, f"{text!r}: Anglo-centric keys on non-Latin input: {sorted(leaked)}"
    assert r.structured.get("phonetic_status") == "not_applicable"
    assert _script_ok(r.structured, SCRIPT_OF[text]), (
        f"{text!r}: script={r.structured.get('script')!r}, want one of {SCRIPT_OF[text]}"
    )


def test_non_latin_family_of_a_full_name_is_marked_too() -> None:
    r = norm("Анна Мария Иванова", F.PERSON_NAME)  # three tokens: parsed, family is Cyrillic
    assert r.normalization_status is NormalizationStatus.PARSED
    assert not set(phonetic("Анна Мария Иванова", F.PERSON_NAME)) & set(fx.LEGACY_KEYS)
    assert r.structured.get("phonetic_status") == "not_applicable"
    assert _script_ok(r.structured, fx.SCRIPT_LABELS["Cyrillic"])


def test_latin_input_is_not_marked_not_applicable() -> None:
    for text in ("Smith", "Muhammad", "Yuri", "O'Brien"):
        assert norm(text).structured.get("phonetic_status") != "not_applicable"


# ---------------------------------------------------------------------------
# (b) CJK / Hangul / Devanagari / Thai: no key at all
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sem", SEMS)
@pytest.mark.parametrize("text", NO_KEY_AT_ALL)
def test_polyphonic_or_unsupported_scripts_emit_no_phonetic_key(text: str, sem: F) -> None:
    r = norm(text, sem)
    assert not codes(text), f"{text!r} must emit no key, got {phonetic(text, sem)}"
    assert not phonetic(text, sem), f"{text!r}: empty/absent phonetic, got {phonetic(text, sem)}"
    assert r.structured.get("phonetic_status") == "not_applicable"


def test_cjk_is_not_given_a_guessed_reading() -> None:
    """Never guess a pinyin/romaji reading for a polyphonic name (single -> Shan or Dan)."""
    for text in fx.CJK_NAMES:
        keys = " ".join(norm(text).structured).lower()
        assert not re.search(r"pinyin|romaji|reading|romani|translit", keys), keys


# ---------------------------------------------------------------------------
# (a'/new keys) language-aware keys exist where the plan says they must
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", LATIN_SPELLINGS)
def test_latin_input_carries_both_language_aware_keys(text: str) -> None:
    ph = phonetic(text)
    for key in fx.NEW_KEYS:
        assert key in ph, f"{text!r}: missing structured['phonetic'][{key!r}]"
        assert _alts(ph[key]), f"{text!r}: empty {key}"


@pytest.mark.parametrize("text", CYRILLIC_ARABIC)
def test_cyrillic_and_arabic_carry_a_language_aware_key(text: str) -> None:
    assert any(codes(text).get(k) for k in fx.NEW_KEYS), f"{text!r}: no language-aware key"


def test_new_keys_only_add_these_names() -> None:
    allowed = {*fx.LEGACY_KEYS, *fx.NEW_KEYS}
    for text in (*LATIN_SPELLINGS, *CYRILLIC_ARABIC):
        assert set(phonetic(text)) <= allowed, (text, sorted(set(phonetic(text)) - allowed))


# ---------------------------------------------------------------------------
# (c) planted same-name pairs: more pairs share a key than the old code; different names never
# ---------------------------------------------------------------------------
def test_baseline_for_this_pair_set_is_what_was_pinned() -> None:
    cross = [p for p in PAIRS if p.a_script != p.b_script]
    got = {
        "pairs": len(PAIRS),
        "soundex": sum(old_shares(p.a, p.b, ("soundex",)) for p in PAIRS),
        "any_legacy": sum(old_shares(p.a, p.b) for p in PAIRS),
        "cross_pairs": len(cross),
        "cross": sum(old_shares(p.a, p.b) for p in cross),
    }
    assert got == _PINNED_BASELINE, got


def test_more_same_name_pairs_share_a_key_than_the_old_code() -> None:
    cross = [p for p in PAIRS if p.a_script != p.b_script]
    now = sum(shares(p.a, p.b) for p in PAIRS)
    now_cross = sum(shares(p.a, p.b) for p in cross)
    msg = (
        f"same-name pairs {len(PAIRS)}: share a key NOW {now} vs old any-key "
        f"{_PINNED_BASELINE['any_legacy']} vs old Soundex {_PINNED_BASELINE['soundex']}; "
        f"cross-script {len(cross)}: NOW {now_cross} vs old {_PINNED_BASELINE['cross']}"
    )
    print(msg)
    assert now > _PINNED_BASELINE["any_legacy"], msg
    assert now > _PINNED_BASELINE["soundex"], msg


def test_elena_yelena_share_a_key() -> None:
    """Phase 0 'no shared key today' pair that ordinary BMPM / Double Metaphone do link."""
    assert shares("Елена", "Yelena")


def test_report_must_fix_pairs() -> None:
    """Reported, not asserted: a faithful BMPM (reference run, scratch env) does NOT link
    Мухаммед (its h-like letter is kh) with Muhammad (h), so the plan's headline example is a
    count target over the whole pair set, not a per-pair requirement (a hand rule to force it
    would be a guess)."""
    print({f"{a}/{b}": shares(a, b) for a, b in fx.MUST_FIX_PAIRS})


@pytest.mark.parametrize(("a", "b"), fx.DIFFERENT_NAME_PAIRS)
def test_different_names_never_share_a_key(a: str, b: str) -> None:
    assert not shares(a, b), f"{a!r}/{b!r} share a key: {codes(a)} {codes(b)}"


# ---------------------------------------------------------------------------
# (d) Latin: every pre-existing output byte-identical to the pre-D11 snapshot
# ---------------------------------------------------------------------------
_SNAP = json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _SNAP, ids=[f"{c['semantic_type']}:{c['input']}" for c in _SNAP])
def test_latin_output_is_byte_identical_to_pre_d11(case: dict[str, Any]) -> None:
    r = norm(case["input"], F[case["semantic_type"]])
    structured = json.loads(json.dumps(r.structured, ensure_ascii=False))
    structured.pop("script", None)
    structured.pop("phonetic_status", None)
    if "phonetic" in structured:
        assert set(structured["phonetic"]) <= {*fx.LEGACY_KEYS, *fx.NEW_KEYS}
        structured["phonetic"] = {
            k: v for k, v in structured["phonetic"].items() if k in fx.LEGACY_KEYS
        }
    assert structured == case["structured"]
    assert (r.display, r.comparison, r.search) == (
        case["display"],
        case["comparison"],
        case["search"],
    )
    assert (r.validation_status, r.normalization_status.value, r.confidence) == (
        case["validation_status"],
        case["normalization_status"],
        case["confidence"],
    )


def test_snapshot_is_substantial_and_covers_diacritics() -> None:
    assert len(_SNAP) >= 60
    inputs = {c["input"] for c in _SNAP}
    assert {"Müller", "José", "Łukasz", "Dvořák"} <= inputs  # Latin script keeps today's keys


# ---------------------------------------------------------------------------
# (e) never guess
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Мухаммед Smith", "Wang 小明", "Smith محمد"])
def test_mixed_script_gets_no_anglo_key_and_no_guess(text: str) -> None:
    r = norm(text)
    assert not set(phonetic(text)) & set(fx.LEGACY_KEYS), phonetic(text)
    assert r.structured.get("phonetic_status") == "not_applicable"


@pytest.mark.parametrize("text", ["12345", "---", "'", "٣٤٥", "..."])
def test_no_letters_means_no_key_and_no_crash(text: str) -> None:
    assert not codes(text)
    assert not set(phonetic(text)) & set(fx.LEGACY_KEYS)


def test_ambiguous_order_still_abstains_for_non_latin_full_names() -> None:
    r = norm("Иван Петров", F.PERSON_NAME)  # two tokens, no comma: order undecidable
    assert r.normalization_status is NormalizationStatus.AMBIGUOUS
    assert not phonetic("Иван Петров", F.PERSON_NAME)
    assert r.structured["given_name"] is None
    assert r.structured["family_name"] is None


def test_language_is_not_guessed_for_ambiguous_latin_names() -> None:
    """'Jose' is Spanish, French (no accent) or an English given name: the output may carry all
    alternatives but must not claim one language."""
    structured = norm("Jose").structured
    assert not {k for k in structured if "language" in k.lower() or k.lower() == "lang"}


# ---------------------------------------------------------------------------
# (f) section 2.4 grep: no hand-written rule rows, no fixture literals, licence + fingerprint
# ---------------------------------------------------------------------------
def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout


def _d11_py_files() -> list[Path]:
    new = [
        ROOT / p
        for p in _git(
            "ls-files", "--others", "--exclude-standard", "--", "packages/normalizers/src"
        ).split()
        if p.endswith(".py")
    ]
    return sorted({*(f for f in D11_FILES if f.exists()), *new})


def _big_literals(path: Path, min_strings: int = 6) -> list[int]:
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        elts = (
            node.elts
            if isinstance(node, ast.List | ast.Tuple | ast.Set)
            else [*node.keys, *node.values]
            if isinstance(node, ast.Dict)
            else []
        )
        if (
            sum(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts)
            >= min_strings
        ):
            out.append(node.lineno)
    return out


def test_no_hand_written_phonetic_rule_rows_in_python() -> None:
    """Rule data is a data file with a NOTICE/licence, or an installed permissive library."""
    for path in _d11_py_files():
        assert not _big_literals(path), (
            f"{path.name}: container literals of >= 6 strings at lines {_big_literals(path)}; "
            "phonetic rules must be a licensed data file or an installed library"
        )
    added = _git("diff", "main", "--", *(str(f) for f in D11_FILES))
    rows = [
        line
        for line in added.splitlines()
        if line.startswith("+")
        and re.match(r'\+\s*\(\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"[^"]*"', line)
    ]
    assert not rows, f"rule-row tuples added: {rows[:3]}"


def _rule_data_files() -> list[Path]:
    """Phonetic rule data under packages/, committed OR not (the old check saw only untracked)."""
    listed = _git(
        "ls-files", "--cached", "--others", "--exclude-standard", "--", "packages", "data"
    )
    return [
        ROOT / p
        for p in listed.split("\n")
        if p
        and re.search(r"bmpm|beider|morse|phonet|metaphone", p, re.I)
        and not p.endswith((".py", ".pyc"))
    ]


def test_rule_data_files_carry_a_licence_notice() -> None:
    data = _rule_data_files()
    if not data:
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        pytest.skip("no rule data file in the tree: an installed library supplies the rules")
    rules = [f for f in data if f.suffix == ".txt"]
    assert rules, "rule data present but no .txt rule files"
    for data_file in data:
        notices = [
            n
            for d in (data_file.parent, *data_file.parents)
            if d.is_relative_to(ROOT)
            for n in d.iterdir()
            if re.match(r"(NOTICE|LICEN[CS]E)", n.name, re.I) and n.is_file()
        ]
        assert notices, f"{data_file}: no NOTICE/LICENSE beside or above it"
        text = "".join(n.read_text(encoding="utf-8", errors="replace") for n in notices)
        assert re.search(r"Apache License|MIT License|BSD|permissive", text), notices
        assert not re.search(r"GNU (Affero |Lesser )?General Public", text), notices
    # a rule file is attributed on its own, so it stays licensed if it is copied out of the tree
    for f in rules:
        head = f.read_text(encoding="utf-8")[:1200]
        assert "Apache License, Version 2.0" in head, f"{f.name}: no per-file licence header"
    # provenance: the NOTICE names where the files came from and a checksum of it
    notice = next(f.parent / "NOTICE" for f in rules if (f.parent / "NOTICE").exists())
    assert re.search(r"\b[0-9a-f]{64}\b", notice.read_text(encoding="utf-8")), "no source sha256"


def test_vendored_rule_files_match_the_upstream_jar() -> None:
    """Byte-identical to the upstream release the NOTICE names (set D11_COMMONS_CODEC_JAR)."""
    jar = os.environ.get("D11_COMMONS_CODEC_JAR")
    if not jar or not Path(jar).exists():
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        pytest.skip("set D11_COMMONS_CODEC_JAR to a commons-codec-1.17.1.jar to compare")
    data = [f for f in _rule_data_files() if f.name.startswith("gen_") and f.suffix == ".txt"]
    notice = (data[0].parent / "NOTICE").read_text(encoding="utf-8")
    assert hashlib.sha256(Path(jar).read_bytes()).hexdigest() in notice
    with zipfile.ZipFile(jar) as z:
        upstream = {n.rsplit("/", 1)[-1]: n for n in z.namelist() if "/language/bm/gen_" in n}
        # the only non-upstream file is the prefix list (it lives in PhoneticEngine.java)
        local_only = {f.name for f in data} - set(upstream)
        assert local_only <= {"gen_name_prefixes.txt"}, local_only
        for f in data:
            if f.name in upstream:
                assert f.read_bytes() == z.read(upstream[f.name]), f.name


def test_no_fixture_literal_in_production_phonetic_code() -> None:
    pattern = re.compile("|".join(re.escape(s) for s in fx.FIXTURE_LITERALS))
    for path in _d11_py_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not line.lstrip().startswith("#"):
                pytest.fail(f"{path.name}:{n} mentions a fixture literal: {line.strip()}")


def test_gpl_abydos_is_not_a_dependency() -> None:
    blob = (ROOT / "pyproject.toml").read_text() + (ROOT / "uv.lock").read_text()
    blob += (ROOT / "packages" / "normalizers" / "pyproject.toml").read_text()
    assert not re.search(r"\babydos\b", blob, re.I)
    for path in _d11_py_files():
        assert "abydos" not in path.read_text(encoding="utf-8").lower()


def _runtime_dependencies(text: str) -> set[str]:
    """Dependency names from the [project] dependencies array only.

    User decision 2026-10-24 (L1: test scope changed with approval, not to
    make it pass): dev-extra tools (deptry, vulture, zizmor, ...) cannot
    change a normalizer's answer, so they are outside ADR-014's contract;
    the old line-regex over the whole file scanned them as if they could.
    """
    m = re.search(r"(?ms)^\[project\]\n(.+?)(?=^\[|\Z)", text)
    if not m:
        return set()
    arr = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)^\]", m.group(1))
    if not arr:
        return set()
    return {
        n.lower().replace("_", "-")
        for n in re.findall(
            r'"([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*(?:[<>=~!]=|[><])', arr.group(1)
        )
    }


def test_added_dependencies_are_fingerprinted() -> None:
    """ADR-014: a package that can change a normalizer's answer moves env_id."""
    # User decision 2026-10-24 (L1: second test edit, approved in chat): "added" means no
    # manifest on main declares it. A member that starts declaring an import it already
    # used (deptry, M4) is not a new package. Compare unions of all manifests.
    rels = [
        "pyproject.toml",
        *sorted(p.relative_to(ROOT).as_posix() for p in ROOT.glob("packages/*/pyproject.toml")),
    ]
    base = next((b for b in ("main", "origin/main") if _git("show", f"{b}:pyproject.toml")), None)
    if base is None:
        # CI fetches main (ci-fast.yml), so a missing ref there is a broken setup, not a skip.
        assert not os.environ.get("CI"), (
            "CI must fetch main: git fetch --no-tags --depth=1 origin main"
        )
        return  # fresh local clone without a main ref: nothing to compare, as before
    on_main: set[str] = set()
    for rel in rels:
        on_main |= _runtime_dependencies(_git("show", f"{base}:{rel}"))
    now: set[str] = set()
    for rel in rels:
        now |= _runtime_dependencies((ROOT / rel).read_text())
    added = now - on_main
    missing = {a for a in added if a not in FINGERPRINTED_PACKAGES and a != "normcore"}
    assert not missing, f"added but not in FINGERPRINTED_PACKAGES: {sorted(missing)}"


def test_license_gate_adds_no_new_violation() -> None:
    done = subprocess.run(
        [sys.executable, "scripts/check_licenses.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    bad = set(re.findall(r"^\s+x ([A-Za-z0-9_.-]+):", done.stdout, re.M))
    # psycopg / psycopg-binary (LGPL) are an environment finding that predates D11.
    assert bad <= {"psycopg", "psycopg-binary"}, f"licence gate blocks: {sorted(bad)}"
