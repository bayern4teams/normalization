"""InMemoryStore <-> normio.SidecarStore wiring (Source.txt §105-§107,
ADR-013) — a run's per-value results survive a restart, closing the gap
disclosed in M9's verification pack.

No live database needed (Parquet + DuckDB are local files under
tmp_path), so these run as fast unit tests. The restart itself is
simulated the same way M9's Postgres persistence tests simulate it: a
SECOND, independent `InMemoryStore` constructed against the same sidecar
paths must see what the first one wrote.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.passthrough import PassthroughNormalizer
from normapi.store import InMemoryStore
from normio.sidecar_store import SidecarStore

from normcore import Dispatcher, ErrorPolicy, FieldSemanticType, NormalizerRegistry


def _dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    return Dispatcher(registry, env_id="e" * 64)


def _store(tmp_path: Path) -> InMemoryStore:
    return InMemoryStore(
        sidecar_parquet_root=tmp_path / "parquet",
        sidecar_duckdb_path=tmp_path / "catalog.duckdb",
    )


@pytest.mark.unit
class TestSidecarWriteOnExecute:
    def test_execute_run_writes_a_real_sidecar_parquet_part(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        dispatcher = _dispatcher()
        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")

        store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="name",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a", "b", "a"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )

        # Read the sidecar directly (bypassing InMemoryStore) to prove the
        # write actually reached real Parquet, not just the in-memory dict.
        sidecar = SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb")
        assert sidecar.find_run_table(run.id) == ("api", "name")
        table = sidecar.read_run(source_id="api", table="name", run_id=run.id)
        assert table.num_rows == 3
        sidecar.close()

    def test_execute_run_without_sidecar_paths_writes_nothing(self, tmp_path: Path) -> None:
        """Every existing test's bare `InMemoryStore()` construction must
        keep behaving exactly as before — no sidecar writes attempted."""
        store = InMemoryStore()  # no sidecar_parquet_root/sidecar_duckdb_path
        dispatcher = _dispatcher()
        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")

        store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="name",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        # Nothing to assert against a sidecar that was never constructed —
        # the absence of a crash/attribute error IS the proof here.
        assert store.get_execution(run.id) is not None


@pytest.mark.unit
class TestRunResultsSurviveARestart:
    """Simulates a real process restart: a SECOND, independent
    InMemoryStore built against the same sidecar paths must be able to
    reconstruct a run's results purely from what the first one wrote."""

    def test_hydrated_execution_matches_the_original_results(self, tmp_path: Path) -> None:
        store_a = _store(tmp_path)
        dispatcher = _dispatcher()
        profile = store_a.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store_a.create_run(
            profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s"
        )
        store_a.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="name",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a", "b", "a", None],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        original_execution = store_a.get_execution(run.id)
        assert original_execution is not None

        # A fresh instance, as a real restart would create — it has never
        # seen this run in-process; the profile/run themselves also don't
        # survive (no postgres_dsn here), but that's this store's own
        # separate concern (M9) — this test is scoped to per-value results.
        store_b = _store(tmp_path)
        store_b._runs[run.id] = store_a.get_run(run.id)

        hydrated = store_b.get_execution(run.id)
        assert hydrated is not None
        assert hydrated.field_name == "name"
        assert hydrated.originals == original_execution.originals
        assert hydrated.results == original_execution.results

    def test_hydrated_execution_reports_zero_sampled_invariants(self, tmp_path: Path) -> None:
        """Runtime invariant sampling only ever happens live, during the
        original execute_run() call — a sidecar-hydrated execution must
        honestly report sampled=0 rather than fabricate a "still clean"
        claim for a run this process never actually executed."""
        store_a = _store(tmp_path)
        dispatcher = _dispatcher()
        profile = store_a.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store_a.create_run(
            profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s"
        )
        store_a.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="name",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )

        store_b = _store(tmp_path)
        store_b._runs[run.id] = store_a.get_run(run.id)

        hydrated = store_b.get_execution(run.id)
        assert hydrated is not None
        assert hydrated.invariant_report.sampled == 0
        assert hydrated.invariant_report.violations == ()

    def test_get_execution_returns_none_when_nothing_was_ever_written(self, tmp_path: Path) -> None:
        """A PENDING run that was never executed stays None even with a
        sidecar configured — no data to hydrate is a real, valid state,
        not an error."""
        store = _store(tmp_path)
        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store.create_run(profile_id=profile.id, env_id="e" * 64, source_snapshot="s")
        assert store.get_execution(run.id) is None
