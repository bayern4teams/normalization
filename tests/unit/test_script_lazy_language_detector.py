"""Phase 3 throughput/memory program prerequisite: ScriptNormalizer's
lingua `LanguageDetector` (`~2.6s` to build, the dominant per-process
memory/startup cost measured in that program) must build lazily, not at
`normalizers.script` module scope — every process-pool worker imports
`normalizers` whether or not it ever normalizes a SCRIPT field, and a
module-scope build cannot be skipped.

Laziness is only observable across a fresh process (a module already
imported once in-process stays imported), so these run `python -c` in a
subprocess rather than asserting against the already-imported module.
"""

from __future__ import annotations

import subprocess
import sys

import normalizers.script as m
import pytest
from normalizers.script import ScriptNormalizer, _get_language_detector
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType


def _ctx() -> NormalizationContext:
    return NormalizationContext(field_name="field", semantic_type=FieldSemanticType.SCRIPT)


@pytest.mark.unit
@pytest.mark.slow_fork
def test_importing_the_module_does_not_build_the_detector() -> None:
    script = (
        "import icu\n"  # DLL load-order guard, see normcli/run_cmd.py
        "import normalizers.script as m\n"
        "assert m._language_detector is None, 'detector built at import time'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


@pytest.mark.unit
@pytest.mark.slow_fork
def test_first_normalize_call_builds_the_detector_exactly_once() -> None:
    script = (
        "import icu\n"
        "import normalizers.script as m\n"
        "from normcore.context import NormalizationContext\n"
        "from normcore.enums import FieldSemanticType\n"
        "ctx = NormalizationContext(field_name='f', semantic_type=FieldSemanticType.SCRIPT)\n"
        "n = m.ScriptNormalizer()\n"
        "assert m._language_detector is None\n"
        "n.normalize('hello world', ctx)\n"
        "assert m._language_detector is not None\n"
        "first = m._language_detector\n"
        "n.normalize('another value', ctx)\n"
        "assert m._language_detector is first, 'detector rebuilt on a later call'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


@pytest.mark.unit
class TestPerColumnLanguageCalibration:
    """Throughput/memory program item 9 (2026-08-29): ScriptNormalizer
    learns a column's likely language set from its own data instead of
    scoring every value against all 75 lingua languages forever. Each
    test uses a unique fake context_hash — `_field_calibrations` is a
    module-level dict with no reset hook, so reusing a hash across tests
    would leak frozen state between them.
    """

    def test_freeze_with_insufficient_diversity_disables_restriction(self) -> None:
        calib = m._FieldCalibration()
        calib.tally = {"ENGLISH": 500}
        m._freeze_calibration(calib)
        assert calib.languages == frozenset()

    def test_freeze_with_no_hits_at_all_disables_restriction(self) -> None:
        calib = m._FieldCalibration()
        m._freeze_calibration(calib)
        assert calib.languages == frozenset()

    def test_freeze_keeps_top_languages_by_count_capped_at_max(self) -> None:
        calib = m._FieldCalibration()
        # One more distinct language than the cap allows.
        calib.tally = {f"LANG{i}": (m._CALIBRATION_MAX_LANGUAGES + 1 - i) for i in range(15)}
        m._freeze_calibration(calib)
        assert calib.languages is not None
        assert len(calib.languages) == m._CALIBRATION_MAX_LANGUAGES
        assert "LANG0" in calib.languages  # highest count, must survive the cut
        assert "LANG14" not in calib.languages  # lowest count, must not

    def test_get_restricted_detector_is_cached_by_language_set(self) -> None:
        d1 = m._get_restricted_detector(frozenset({"ENGLISH", "FRENCH"}))
        d2 = m._get_restricted_detector(frozenset({"ENGLISH", "FRENCH"}))
        assert d1 is d2

    def test_calibration_warms_up_then_freezes_and_reuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(m, "_CALIBRATION_SAMPLES", 3)
        context_hash = "test-warmup-hash-1"

        for _ in range(3):
            m._detect_language_hint("hello there friend", context_hash)

        calib = m._get_field_calibration(context_hash)
        assert calib.languages is not None  # frozen after exactly _CALIBRATION_SAMPLES samples

        # A later call for the SAME column must not grow the tally further
        # (calibration only runs during warm-up).
        seen_before = dict(calib.tally)
        m._detect_language_hint("hello there friend", context_hash)
        assert calib.tally == seen_before

    def test_calibration_is_independent_per_column(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "_CALIBRATION_SAMPLES", 2)
        hash_a, hash_b = "test-independent-a", "test-independent-b"

        for _ in range(2):
            m._detect_language_hint("hello there friend", hash_a)
        calib_a = m._get_field_calibration(hash_a)
        calib_b = m._get_field_calibration(hash_b)

        assert calib_a.languages is not None  # warmed up
        assert calib_b.languages is None  # untouched — never called for hash_b

    def test_low_confidence_restricted_result_falls_back_to_full_detector(self) -> None:
        context_hash = "test-fallback-hash-1"
        calib = m._get_field_calibration(context_hash)
        # Freeze straight to a language set that excludes French, forcing
        # the fallback branch. Needs enough candidate languages that one
        # doesn't win by default on a small pool alone (empirically, a
        # 2-language restricted set still gave the French sentence below
        # a spuriously high ~0.68 "confidence" against two unrelated
        # languages -- real calibration output is never that small, see
        # test_freeze_keeps_top_languages_by_count_capped_at_max).
        calib.languages = frozenset(
            {"ENGLISH", "GERMAN", "DUTCH", "SWEDISH", "ITALIAN", "SPANISH", "PORTUGUESE", "POLISH"}
        )
        calib.detector = None

        value = "Jean-Luc est alle au marche hier matin avec sa mere"
        restricted_only = m._score(m._get_restricted_detector(calib.languages), value)
        full_result = m._score(m._get_language_detector(), value)
        got = m._detect_language_hint(value, context_hash)

        assert restricted_only[1] < m._FALLBACK_CONFIDENCE_THRESHOLD  # the premise
        assert got == full_result  # fell back, not the low-confidence restricted answer


@pytest.mark.unit
def test_get_language_detector_is_idempotent_in_process() -> None:
    first = _get_language_detector()
    second = _get_language_detector()
    assert first is second


@pytest.mark.unit
def test_normalize_output_unaffected_by_laziness() -> None:
    normalizer = ScriptNormalizer()
    result = normalizer.normalize("مرحبا", _ctx())
    assert result.structured["script"] == "Arabic"


@pytest.mark.unit
@pytest.mark.slow_fork
@pytest.mark.parametrize("workers", [4])
def test_concurrent_first_callers_share_one_build(workers: int) -> None:
    script = (
        "import icu\n"
        "import threading\n"
        "import normalizers.script as m\n"
        "from normcore.context import NormalizationContext\n"
        "from normcore.enums import FieldSemanticType\n"
        "ctx = NormalizationContext(field_name='f', semantic_type=FieldSemanticType.SCRIPT)\n"
        "n = m.ScriptNormalizer()\n"
        "seen = []\n"
        "def hit():\n"
        "    n.normalize('concurrent value', ctx)\n"
        "    seen.append(id(m._language_detector))\n"
        f"threads = [threading.Thread(target=hit) for _ in range({workers})]\n"
        "[t.start() for t in threads]\n"
        "[t.join() for t in threads]\n"
        "assert len(set(seen)) == 1, f'multiple detector instances built: {seen}'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
