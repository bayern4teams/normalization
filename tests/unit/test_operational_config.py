"""Four pieces of operational debt, fixed together.

They share a theme: a value that looked settled but was not observable or
not tunable — one constant driving four unrelated decisions, a job that
could die without anyone being able to tell, a fingerprint that was the
same everywhere, and config that existed only as a literal in Python.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import blake3
import pytest
from normapi.app import _resolve_env_id
from normexec.env_fingerprint import (
    FINGERPRINTED_PACKAGES,
    EnvFingerprintInputs,
    compute_env_id,
)
from normio.connectors import _sql_base

from normapi import clone_executor

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
class TestRowBatchingKnobs:
    """One `ROW_CHUNK_SIZE` drove the source read batch, the insert
    transaction boundary, the persistence write chunk and the read page
    size, so tuning any one of them silently moved the other three."""

    @pytest.mark.parametrize(
        "name",
        [
            "SOURCE_READ_BATCH_ROWS",
            "DESTINATION_INSERT_CHUNK_ROWS",
            "PERSISTENCE_WRITE_CHUNK_ROWS",
            "PERSISTENCE_PAGE_ROWS",
        ],
    )
    def test_each_purpose_has_its_own_knob(self, name: str) -> None:
        assert getattr(_sql_base, name) > 0

    def test_defaults_are_unchanged(self) -> None:
        """Splitting the constant must not change behaviour on its own."""
        for name in (
            "SOURCE_READ_BATCH_ROWS",
            "DESTINATION_INSERT_CHUNK_ROWS",
            "PERSISTENCE_WRITE_CHUNK_ROWS",
            "PERSISTENCE_PAGE_ROWS",
        ):
            assert getattr(_sql_base, name) == _sql_base.ROW_CHUNK_SIZE

    @pytest.mark.parametrize(("value", "expected"), [("500", 500), ("1", 1)])
    def test_environment_overrides(self, monkeypatch, value: str, expected: int) -> None:
        monkeypatch.setenv("NORM_TEST_ROWS", value)
        assert _sql_base._env_rows("NORM_TEST_ROWS", 2000) == expected

    @pytest.mark.parametrize("value", ["", "2k", "abc", "0", "-5", "3.5"])
    def test_an_unusable_override_falls_back_instead_of_crashing(
        self, monkeypatch, value: str
    ) -> None:
        """A typo in an env var must not take the process down at import
        time — the tested default is strictly better than refusing to
        start."""
        monkeypatch.setenv("NORM_TEST_ROWS", value)
        assert _sql_base._env_rows("NORM_TEST_ROWS", 2000) == 2000

    def test_unset_uses_the_default(self, monkeypatch) -> None:
        monkeypatch.delenv("NORM_TEST_ROWS", raising=False)
        assert _sql_base._env_rows("NORM_TEST_ROWS", 2000) == 2000


@pytest.mark.unit
class TestCloneJobStaleness:
    """A job whose PROCESS is killed (OOM, container restart) never runs
    the `except` that marks it FAILED, so it sits in RUNNING forever,
    indistinguishable from a job that is merely slow."""

    @staticmethod
    def _at(seconds_ago: int) -> str:
        moment = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=seconds_ago)
        return moment.isoformat()

    def test_a_running_job_that_stopped_checkpointing_is_stale(self) -> None:
        job = {
            "status": "RUNNING",
            "heartbeat_at": self._at(clone_executor.HEARTBEAT_TIMEOUT_SECONDS + 60),
        }
        assert clone_executor.is_stale(job) is True

    def test_a_running_job_still_checkpointing_is_not(self) -> None:
        assert clone_executor.is_stale({"status": "RUNNING", "heartbeat_at": self._at(5)}) is False

    @pytest.mark.parametrize("status", ["COMPLETED", "FAILED", "SCHEMA_READY", "PENDING_DB_CREATE"])
    def test_only_running_jobs_can_be_stale(self, status: str) -> None:
        job = {"status": status, "heartbeat_at": self._at(999_999)}
        assert clone_executor.is_stale(job) is False

    def test_a_job_with_no_heartbeat_is_unknown_not_stale(self) -> None:
        """Jobs written before heartbeats existed would otherwise all be
        reported dead."""
        assert clone_executor.is_stale({"status": "RUNNING"}) is False

    def test_a_corrupt_heartbeat_is_not_stale(self) -> None:
        assert clone_executor.is_stale({"status": "RUNNING", "heartbeat_at": "nope"}) is False

    def test_staleness_never_rewrites_the_job(self) -> None:
        """Advisory by design: claiming already allows RUNNING -> RUNNING,
        so a stale job is restarted, not resurrected by a sweeper that
        cannot know whether the source is just slow."""
        job = {"status": "RUNNING", "heartbeat_at": self._at(999_999)}
        clone_executor.is_stale(job)
        assert job["status"] == "RUNNING"


@pytest.mark.unit
class TestEnvIdIsReal:
    """The API stamped `blake3(b"normapi-m1-scaffold-env-id")` — the same
    hash in every environment, for every dictionary and dependency
    version. As a cache key that is worse than useless: ADR-014 exists to
    stop a result computed elsewhere being replayed as current."""

    @staticmethod
    def _inputs(**overrides) -> EnvFingerprintInputs:
        base = {
            "packages": {"dateparser": "1.4.2"},
            "icu_version": "78.3",
            "dictionaries": {"missing-values.common@2026.08": "abc"},
            "profile_version": "v1",
        }
        return EnvFingerprintInputs(**{**base, **overrides})

    def test_api_env_id_is_not_the_old_placeholder(self) -> None:
        placeholder = blake3.blake3(b"normapi-m1-scaffold-env-id").hexdigest()
        assert _resolve_env_id() != placeholder

    def test_api_env_id_is_stable_within_an_environment(self) -> None:
        assert _resolve_env_id() == _resolve_env_id()

    def test_a_dictionary_change_changes_env_id(self) -> None:
        a = compute_env_id(self._inputs())
        b = compute_env_id(self._inputs(dictionaries={"missing-values.common@2026.08": "xyz"}))
        assert a != b

    def test_a_package_version_change_changes_env_id(self) -> None:
        a = compute_env_id(self._inputs())
        b = compute_env_id(self._inputs(packages={"dateparser": "1.4.3"}))
        assert a != b

    def test_edtf_participates_in_the_fingerprint(self) -> None:
        """It changes DATE output, so a version bump must invalidate
        cached dates — the inventory and this list must stay in step."""
        assert "edtf" in FINGERPRINTED_PACKAGES

    def test_the_script_and_the_module_are_one_implementation(self) -> None:
        """Two copies would drift, and a drifted env_id is a silent
        reproducibility bug."""
        source = (_ROOT / "scripts" / "env_fingerprint.py").read_text()
        assert "from normexec.env_fingerprint import" in source
        assert "blake3.blake3(canonical" not in source


@pytest.mark.unit
class TestEnvExampleDocumentsEveryVariable:
    def test_every_norm_variable_used_in_code_is_documented(self) -> None:
        """An undocumented knob is one an operator cannot find."""
        documented = set(
            re.findall(r"^(NORM_[A-Z0-9_]+)=", (_ROOT / ".env.example").read_text(), re.M)
        )
        used: set[str] = set()
        for path in (_ROOT / "packages").rglob("*.py"):
            used |= set(re.findall(r'"(NORM_[A-Z0-9_]+)"', path.read_text(encoding="utf-8")))
        assert used - documented == set()
