"""Integration tests against the REAL metadata Postgres (compose.yaml's
`postgres` service, port 5535 on the host) — Source.txt §105-§107,
docs/adr/ADR-013-normalization-storage.md, M9.

Two things are proven per component, not assumed:
1. `PostgresMetadataStore` itself — real round-trips through a real
   database, not a mock.
2. `InMemoryStore(postgres_dsn=...)`'s write-through + startup hydration
   — the actual "survives a restart" behavior end-to-end, simulated by
   constructing a SECOND, independent `InMemoryStore` against the same
   DSN and confirming it sees what the first one wrote, exactly as a
   real process restart would.

Requires: docker compose up -d postgres
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from normapi.postgres_store import PostgresMetadataStore
from normapi.store import InMemoryStore

from normcore import NormalizationProfile, NormalizationRun, NormalizationRunMetrics, RunStatus

_PG_DSN = os.environ.get(
    "TEST_METADATA_PG_DSN", "postgresql://normalization:normalization@localhost:5535/normalization"
)


@pytest.fixture
def pg_store() -> Iterator[PostgresMetadataStore]:
    try:
        store = PostgresMetadataStore(_PG_DSN)
    except psycopg.OperationalError as exc:
        pytest.skip(f"metadata postgres not reachable at {_PG_DSN}: {exc}")
    yield store
    store.close()


def _profile(profile_id: str, version: str = "v1") -> NormalizationProfile:
    return NormalizationProfile(
        id=profile_id,
        name="test",
        version=version,
        created_at="2026-08-19T00:00:00Z",
        updated_at="2026-08-19T00:00:00Z",
        created_by="test",
    )


def _run(run_id: str, profile_id: str) -> NormalizationRun:
    return NormalizationRun(
        id=run_id,
        profile_id=profile_id,
        profile_version="v1",
        env_id="e" * 64,
        source_snapshot="s",
        started_at="2026-08-19T00:00:00Z",
        status=RunStatus.PENDING,
        metrics=NormalizationRunMetrics(),
    )


@pytest.mark.integration
class TestPostgresMetadataStoreDirect:
    def test_save_and_get_profile_round_trips(self, pg_store: PostgresMetadataStore) -> None:
        profile_id = str(uuid.uuid4())
        profile = _profile(profile_id)
        pg_store.save_profile(profile)

        loaded = pg_store.get_profile(profile_id, "v1")
        assert loaded is not None
        assert loaded == profile

    def test_get_profile_returns_none_for_unknown(self, pg_store: PostgresMetadataStore) -> None:
        assert pg_store.get_profile(str(uuid.uuid4()), "v1") is None

    def test_save_profile_upserts_on_conflict(self, pg_store: PostgresMetadataStore) -> None:
        profile_id = str(uuid.uuid4())
        pg_store.save_profile(_profile(profile_id))
        updated = _profile(profile_id).model_copy(update={"description": "changed"})
        pg_store.save_profile(updated)

        loaded = pg_store.get_profile(profile_id, "v1")
        assert loaded is not None
        assert loaded.description == "changed"

    def test_list_profile_versions_returns_all_versions_in_order(
        self, pg_store: PostgresMetadataStore
    ) -> None:
        profile_id = str(uuid.uuid4())
        pg_store.save_profile(_profile(profile_id, "v1"))
        pg_store.save_profile(_profile(profile_id, "v2"))

        versions = pg_store.list_profile_versions(profile_id)
        assert [p.version for p in versions] == ["v1", "v2"]

    def test_active_version_round_trips(self, pg_store: PostgresMetadataStore) -> None:
        profile_id = str(uuid.uuid4())
        pg_store.save_profile(_profile(profile_id))
        pg_store.set_active_version(profile_id, "v1")

        assert pg_store.get_active_version(profile_id) == "v1"

    def test_active_version_upserts_on_conflict(self, pg_store: PostgresMetadataStore) -> None:
        profile_id = str(uuid.uuid4())
        pg_store.save_profile(_profile(profile_id, "v1"))
        pg_store.save_profile(_profile(profile_id, "v2"))
        pg_store.set_active_version(profile_id, "v1")
        pg_store.set_active_version(profile_id, "v2")

        assert pg_store.get_active_version(profile_id) == "v2"

    def test_profile_exists(self, pg_store: PostgresMetadataStore) -> None:
        profile_id = str(uuid.uuid4())
        assert pg_store.profile_exists(profile_id) is False
        pg_store.save_profile(_profile(profile_id))
        assert pg_store.profile_exists(profile_id) is True

    def test_save_and_get_run_round_trips(self, pg_store: PostgresMetadataStore) -> None:
        profile_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        pg_store.save_profile(_profile(profile_id))
        run = _run(run_id, profile_id)
        pg_store.save_run(run)

        loaded = pg_store.get_run(run_id)
        assert loaded is not None
        assert loaded == run

    def test_save_run_upserts_on_conflict(self, pg_store: PostgresMetadataStore) -> None:
        profile_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        pg_store.save_profile(_profile(profile_id))
        pg_store.save_run(_run(run_id, profile_id))
        finished = _run(run_id, profile_id).model_copy(update={"status": RunStatus.COMPLETED})
        pg_store.save_run(finished)

        loaded = pg_store.get_run(run_id)
        assert loaded is not None
        assert loaded.status is RunStatus.COMPLETED

    def test_list_all_profiles_and_list_runs(self, pg_store: PostgresMetadataStore) -> None:
        profile_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        pg_store.save_profile(_profile(profile_id))
        pg_store.save_run(_run(run_id, profile_id))

        all_profile_ids = {p.id for p in pg_store.list_all_profiles()}
        all_run_ids = {r.id for r in pg_store.list_runs()}
        assert profile_id in all_profile_ids
        assert run_id in all_run_ids

    def test_list_active_profiles_only_returns_active_versions(
        self, pg_store: PostgresMetadataStore
    ) -> None:
        profile_id = str(uuid.uuid4())
        pg_store.save_profile(_profile(profile_id, "v1"))
        pg_store.save_profile(_profile(profile_id, "v2"))
        pg_store.set_active_version(profile_id, "v2")

        active = {p.id: p.version for p in pg_store.list_active_profiles()}
        assert active[profile_id] == "v2"


@pytest.mark.integration
class TestInMemoryStorePersistenceAcrossInstances:
    """Simulates a real process restart: a SECOND, independent
    InMemoryStore constructed against the same Postgres DSN must see
    everything the first one wrote — the actual promise this milestone
    delivers."""

    def test_profile_created_by_one_store_is_visible_from_a_second(self) -> None:
        try:
            store_a = InMemoryStore(postgres_dsn=_PG_DSN)
        except psycopg.OperationalError as exc:
            pytest.skip(f"metadata postgres not reachable at {_PG_DSN}: {exc}")

        profile = store_a.create_profile(
            name="restart-test",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )

        # A fresh instance, as a real restart would create — hydrates
        # from Postgres in __init__, before serving any request.
        store_b = InMemoryStore(postgres_dsn=_PG_DSN)
        recovered = store_b.get_profile(profile.id)
        assert recovered == profile

    def test_run_record_created_by_one_store_is_visible_from_a_second(self) -> None:
        try:
            store_a = InMemoryStore(postgres_dsn=_PG_DSN)
        except psycopg.OperationalError as exc:
            pytest.skip(f"metadata postgres not reachable at {_PG_DSN}: {exc}")

        profile = store_a.create_profile(
            name="restart-test-run",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store_a.create_run(profile_id=profile.id, env_id="e" * 64, source_snapshot="s")

        store_b = InMemoryStore(postgres_dsn=_PG_DSN)
        recovered = store_b.get_run(run.id)
        assert recovered == run

    def test_profile_version_and_rollback_survive_a_restart(self) -> None:
        try:
            store_a = InMemoryStore(postgres_dsn=_PG_DSN)
        except psycopg.OperationalError as exc:
            pytest.skip(f"metadata postgres not reachable at {_PG_DSN}: {exc}")

        profile = store_a.create_profile(
            name="restart-test-version",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        store_a.create_version(
            profile.id,
            description="v2",
            locale_policy=None,
            default_operations=None,
            field_configs=None,
            created_by="u",
        )
        store_a.rollback_profile(profile.id, "v1")

        store_b = InMemoryStore(postgres_dsn=_PG_DSN)
        versions = store_b.list_profile_versions(profile.id)
        assert {v.version for v in versions} == {"v1", "v2"}
        active = store_b.get_profile(profile.id)  # no version -> resolves active
        assert active.version == "v1"
        assert active.status.value == "ACTIVE"
