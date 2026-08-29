"""normcli run — executes a normalization profile against a source end
to end, outside the FastAPI/HTTP layer, writing results to a directory
`diff_cmd.py` can compare across two independent runs. Built for
ADR-014's byte-identical-replay determinism gate
(`.github/workflows/gate.yml`'s `determinism-replay` job), which has
invoked `normcli run`/`normcli diff --require-identical` since M13-M22
was drafted without either command existing (`normcli/cli.py` only had
`check-traceability` and `mutation-score-gate` until the 2026-08-29
throughput R&D pass found the gap).

Composes the same execution primitives the real HTTP API's multi-column
run path composes (`packages/normapi/src/normapi/store.py`'s
`_run_multi_column_one_column`), minus the parts that exist only to
serve untrusted HTTP callers (encrypted connection registry, thread-pool
dispatch): `normexec.stream.stream_column` and `normio`'s connectors are
already fully decoupled from FastAPI/Postgres-metadata — confirmed by
`tests/integration/test_stream_column.py`, which exercises the same
primitives with zero HTTP/registry involvement.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

# Import order guard — MUST run before `pyarrow` is imported anywhere in
# this process, or PyICU's and PyArrow's bundled native DLLs conflict on
# Windows (segfault). See ADR-001's DLL-load-order addendum and
# tests/integration/fixtures/run_passthrough_demo.py's identical comment
# — normalizers/normexec/normio all import pyarrow transitively, so this
# must be the first third-party import in this module.
import icu  # noqa: F401
from normalizers.address import LibpostalClient
from normexec.sinks import SidecarRunSink
from normexec.stream import stream_column
from normio.connectors.postgres import PostgresConnector
from normio.sidecar_store import SidecarStore

from normanalysis import RunRecorder
from normcli.demo_fixture import resolve_profile, resolve_source_dsn
from normcli.registry import (
    DEFAULT_DICTIONARIES_DIR,
    DEFAULT_LIBPOSTAL_URL,
    build_normalizer_registry,
    compute_process_env_id,
)
from normcore import Dispatcher, NormalizationRun, NormalizationRunMetrics, RunStatus


class UnknownFieldRefError(ValueError):
    pass


@dataclass(frozen=True)
class RunResult:
    run: NormalizationRun
    rows_processed: int
    out_dir: Path


def _parse_field_ref(field_ref: str) -> tuple[str, str, str]:
    """"{source}.{table}.{column}" -> (source, table, column) — the CLI's
    own convention (there is no DB-registered `connection_identity` to
    key off of here, unlike the HTTP API's field_ref shape at
    `packages/normapi/src/normapi/store.py:1077`)."""
    parts = field_ref.split(".")
    if len(parts) != 3:
        msg = f"Malformed field_ref {field_ref!r} — expected 'source.table.column'"
        raise UnknownFieldRefError(msg)
    return parts[0], parts[1], parts[2]


def _write_run_report(out_dir: Path, run: NormalizationRun) -> None:
    (out_dir / "run_report.json").write_text(
        json.dumps(run.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8"
    )


def run_normalization(
    *,
    profile_name: str,
    source_name: str,
    out_dir: Path,
    run_id: str = "normcli-run",
    dsn: str | None = None,
    dictionaries_dir: Path | None = None,
    libpostal_url: str | None = None,
    chunk_size: int = 100_000,
) -> RunResult:
    profile = resolve_profile(profile_name)
    resolved_dsn = dsn if dsn is not None else resolve_source_dsn(source_name)
    resolved_dictionaries_dir = dictionaries_dir or DEFAULT_DICTIONARIES_DIR
    resolved_libpostal_url = libpostal_url or DEFAULT_LIBPOSTAL_URL

    libpostal_client = LibpostalClient(resolved_libpostal_url)
    registry = build_normalizer_registry(resolved_dictionaries_dir, libpostal_client)
    env_id = compute_process_env_id(
        dictionaries_dir=resolved_dictionaries_dir, libpostal_client=libpostal_client
    )
    dispatcher = Dispatcher(registry, env_id=env_id)

    out_dir.mkdir(parents=True, exist_ok=True)
    connector = PostgresConnector(source_name, resolved_dsn)
    try:
        sidecar = SidecarStore(out_dir / "parquet", out_dir / "catalog.duckdb")
        try:
            sink = SidecarRunSink(sidecar, source_id=source_name)
            run = NormalizationRun(
                id=run_id,
                profile_id=profile.id,
                profile_version=profile.version,
                env_id=env_id,
                source_snapshot=source_name,
                started_at=datetime.now(UTC).isoformat(),
                status=RunStatus.PENDING,
                metrics=NormalizationRunMetrics(),
            )
            recorder = RunRecorder(run)
            recorder.start()

            total_rows = 0
            try:
                for field_config in profile.field_configs:
                    _source, table, column = _parse_field_ref(field_config.field_ref)
                    known_columns = {c.name for c in connector.list_columns(table)}
                    if column not in known_columns:
                        msg = (
                            f"Profile {profile.id!r} references {table}.{column}, which does "
                            f"not exist in source {source_name!r} "
                            f"(columns: {sorted(known_columns)})"
                        )
                        raise UnknownFieldRefError(msg)

                    key_columns = list(connector.table_spec(table).primary_key)
                    if not key_columns:
                        msg = (
                            f"Table {table!r} has no declared primary key; "
                            "cannot be streamed chunk by chunk"
                        )
                        raise UnknownFieldRefError(msg)

                    ctx = profile.build_context(field_config.field_ref, field_config.semantic_type)
                    total_rows += stream_column(
                        connector,
                        run_id=run_id,
                        table=table,
                        column=column,
                        key_columns=key_columns,
                        semantic_type=field_config.semantic_type,
                        context=ctx,
                        profile=profile,
                        dispatcher=dispatcher,
                        # A bare CLI run measures the source + engine, not a
                        # warmed cache — two independent processes each
                        # start cold regardless, so this has no effect on
                        # the determinism this command exists to prove.
                        cache=None,
                        recorder=recorder,
                        sink=sink,
                        chunk_size=chunk_size,
                    )
                finished_run = recorder.finish(RunStatus.COMPLETED)
            except Exception as exc:
                finished_run = recorder.finish(RunStatus.FAILED).model_copy(
                    update={"failure_reason": str(exc)}
                )
                raise
            finally:
                _write_run_report(out_dir, finished_run)
        finally:
            sidecar.close()
    finally:
        connector.close()

    return RunResult(run=finished_run, rows_processed=total_rows, out_dir=out_dir)


def run_normalization_cli(
    *,
    profile_name: str,
    source_name: str,
    out_dir: Path,
    run_id: str,
    dsn: str | None,
    stream: TextIO | None = None,
) -> int:
    """Returns a process exit code (0 = pass), matching this package's
    other `run_*` gate functions' shape."""
    out = stream if stream is not None else sys.stdout
    try:
        result = run_normalization(
            profile_name=profile_name,
            source_name=source_name,
            out_dir=out_dir,
            run_id=run_id,
            dsn=dsn,
        )
    except Exception as exc:
        out.write(f"run: ERROR: {exc}\n")
        return 2

    out.write(
        f"run: {result.run.status.value} — {result.rows_processed} rows "
        f"written to {result.out_dir}\n"
    )
    return 0 if result.run.status is RunStatus.COMPLETED else 1
