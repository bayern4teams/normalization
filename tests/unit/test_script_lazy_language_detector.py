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
