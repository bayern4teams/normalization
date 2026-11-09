"""D25: API start-up read the whole adjudication queue into memory, so a queue
of 2.1M rows OOM-killed the API before /health answered (FINAL_REPORT §5.6)."""

from __future__ import annotations

import json
import tracemalloc
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from normapi.adjudication import migrate_sources
from normapi.app import create_app
from normapi.pg_persistence import PgPersistence

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_ROWS = 5000
_ROW_BYTES = 20_000
# The queue holds about 100 MB; start-up may not hold more than a sliver of it.
_MAX_GROWTH_BYTES = 5_000_000
_INSERT = sa.text(
    "INSERT INTO normalization_adjudication_queue (key, semantic_type, context_hash, "
    "profile_version, context, original, detail, first_job_id, last_job_id, occurrences) "
    "VALUES (:key, 'DATE', 'h', 'p', :context, 'o', :detail, 'j', 'j', 1)"
)


def _store(path: Path) -> PgPersistence:
    store = PgPersistence(f"sqlite:///{path}")
    store.ensure_schema()
    return store


def _row(key: str, context: dict[str, str], detail: str = "{}") -> dict[str, str]:
    return {"key": key, "context": json.dumps(context), "detail": detail}


def _start_peak(path: Path) -> int:
    """Peak Python memory of one API start-up on the metadata database at `path`."""
    tracemalloc.start()
    try:
        create_app(
            pg_dsn=f"sqlite:///{path}",
            dictionaries_dir=path.parent / "dicts",
            custom_dictionaries_dir=path.parent / "custom",
        )
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_start_up_does_not_load_a_queue_with_nothing_to_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())
    empty, full = tmp_path / "empty.db", tmp_path / "full.db"
    _store(empty)
    store = _store(full)
    # json.dumps keeps the detail valid, so a whole-queue read would parse it.
    detail = json.dumps({"pad": "x" * _ROW_BYTES})
    with store._engine.begin() as conn:
        conn.execute(
            _INSERT,
            [_row(f"k{i}", {"source": "postgres://db:5432/x"}, detail) for i in range(_ROWS)],
        )

    _start_peak(empty)  # warms import-time caches, so the two runs compare alike
    baseline = _start_peak(empty)
    assert _start_peak(full) - baseline < _MAX_GROWTH_BYTES


def test_only_the_source_field_decides_whether_a_row_needs_migrating(tmp_path: Path) -> None:
    store = _store(tmp_path / "m.db")
    with store._engine.begin() as conn:
        conn.execute(
            _INSERT,
            [
                # "://" in another field must not hide a row still keyed by connection id.
                _row("legacy", {"source": "conn-gone", "note": "http://example"}),
                _row("no-source", {"note": "x"}),
                _row("blank", {"source": ""}),
                _row("done", {"source": "postgres://db:5432/x"}),
            ],
        )
    assert migrate_sources(store) == {"migrated": 0, "unmigrated": 1}
