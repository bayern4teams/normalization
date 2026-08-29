"""Confirms `normapi.app.create_app()`'s Phase 3 process-pool wiring
(throughput/memory program, 2026-08-29): off by default, and a real,
usable `DistinctValueWorkerPool` when explicitly configured — not just
that the plumbing type-checks.
"""

from __future__ import annotations

from pathlib import Path

import icu  # noqa: F401 - DLL load-order guard, see normcli/run_cmd.py
import pytest
from normapi.app import create_app
from normcore.context import NormalizationContext
from normcore.rules import NormalizationProfile
from normexec.parallel import DistinctValueWorkerPool

from normcore import FieldSemanticType


@pytest.fixture
def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    dict_dir = tmp_path / "dictionaries"
    dict_dir.mkdir()
    custom_dict_dir = tmp_path / "custom-dictionaries"
    return dict_dir, custom_dict_dir


@pytest.mark.unit
def test_parallel_pool_is_none_by_default(_dirs: tuple[Path, Path]) -> None:
    dict_dir, custom_dict_dir = _dirs
    app = create_app(dictionaries_dir=dict_dir, custom_dictionaries_dir=custom_dict_dir)
    assert app.state.parallel_pool is None
    assert app.state.store._parallel_pool is None


@pytest.mark.unit
def test_parallel_pool_disabled_when_env_var_unset(
    monkeypatch: pytest.MonkeyPatch, _dirs: tuple[Path, Path]
) -> None:
    monkeypatch.delenv("NORM_PARALLEL_WORKERS", raising=False)
    dict_dir, custom_dict_dir = _dirs
    app = create_app(dictionaries_dir=dict_dir, custom_dictionaries_dir=custom_dict_dir)
    assert app.state.parallel_pool is None


@pytest.mark.unit
@pytest.mark.slow_fork
def test_parallel_pool_is_real_and_functional_when_explicitly_configured(
    _dirs: tuple[Path, Path],
) -> None:
    """`parallel_workers=1` builds a REAL pool with the REAL 20-normalizer
    registry (the same `build_worker_dispatcher` path a live deployment
    would use) — proving the wiring produces something usable, not just
    an object of the right type. Slow (~real worker startup) by nature;
    kept to a single worker to bound that cost."""
    dict_dir, custom_dict_dir = _dirs
    app = create_app(
        dictionaries_dir=dict_dir, custom_dictionaries_dir=custom_dict_dir, parallel_workers=1
    )
    pool = app.state.parallel_pool
    try:
        assert isinstance(pool, DistinctValueWorkerPool)
        assert pool.workers == 1
        assert app.state.store._parallel_pool is pool

        ctx = NormalizationContext(field_name="f", semantic_type=FieldSemanticType.COUNTRY)
        profile = NormalizationProfile(
            id="p1",
            name="test",
            version="v1",
            created_at="2026-08-29T00:00:00Z",
            updated_at="2026-08-29T00:00:00Z",
            created_by="test",
        )
        results = pool.normalize_batch(["US", "DE"], FieldSemanticType.COUNTRY, ctx, profile)
        assert len(results) == 2
    finally:
        pool.shutdown()
