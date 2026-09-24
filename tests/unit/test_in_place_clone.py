"""In-place normalization: normalize the source database itself instead
of cloning it into a second one.

The point is storage. A clone needs room for a whole second copy of the
source; in-place builds ONE table beside its original, swaps it in and
drops the original, so peak extra storage is the largest single table.
"""

from __future__ import annotations

import pytest
from normapi.clone_executor import staging_name
from normapi.schemas import CloneJobCreateRequest
from pydantic import ValidationError


@pytest.mark.unit
class TestInPlaceRequest:
    def test_destination_is_optional_for_in_place(self) -> None:
        request = CloneJobCreateRequest(
            source_connection_id="c1", source_database="db", in_place=True
        )
        assert request.in_place is True

    def test_destination_is_required_for_a_normal_clone(self) -> None:
        """Without this the executor fails later with "no such
        connection: ''", which says nothing useful."""
        with pytest.raises(ValidationError):
            CloneJobCreateRequest(source_connection_id="c1", source_database="db")

    def test_clone_still_requires_both_destination_fields(self) -> None:
        with pytest.raises(ValidationError):
            CloneJobCreateRequest(
                source_connection_id="c1",
                source_database="db",
                destination_connection_id="c2",
            )

    def test_in_place_is_off_by_default(self) -> None:
        """It REPLACES the source; originals survive only in the error
        report. Never a default, never inferred."""
        request = CloneJobCreateRequest(
            source_connection_id="c1",
            source_database="db",
            destination_connection_id="c2",
            destination_database="clone",
        )
        assert request.in_place is False


@pytest.mark.unit
class TestStagingName:
    def test_staging_name_is_distinct_from_the_table(self) -> None:
        assert staging_name("Company") != "Company"

    def test_staging_name_is_stable(self) -> None:
        """Phase 1 creates it and Phase 2 fills and swaps it, in separate
        processes — so it must be derived, not remembered."""
        assert staging_name("Company") == staging_name("Company")


@pytest.mark.unit
class TestInPlaceJobWiring:
    """`create_clone_job` derives the destination for in-place rather than
    trusting the request."""

    @staticmethod
    def _make_job(monkeypatch, **overrides):
        from normapi import clone_executor

        class _Source:
            def list_tables(self):
                return ["Company"]

            def close(self):
                pass

        class _Persistence:
            def __init__(self):
                self.saved = {}

            def get_connection(self, connection_id):
                return {"connection_id": connection_id, "engine": "postgres"}

            def create_clone_job(self, job_id, job):
                self.saved[job_id] = job

        monkeypatch.setattr(clone_executor, "build_source_connector", lambda *a, **k: _Source())
        request = {
            "source_connection_id": "src",
            "source_database": "sourcedb",
            "destination_connection_id": "dst",
            "destination_database": "clonedb",
            "field_configs": {},
            "autodetect_field_types": False,
            **overrides,
        }
        return clone_executor.create_clone_job(_Persistence(), request=request)

    def test_in_place_job_targets_the_source(self, monkeypatch) -> None:
        """A typo in destination_database would otherwise write staging
        tables into some other database and swap nothing."""
        job = self._make_job(monkeypatch, in_place=True)
        assert job["destination_database"] == "sourcedb"
        assert job["destination_connection_id"] == "src"
        assert job["in_place"] is True

    def test_normal_job_keeps_the_requested_destination(self, monkeypatch) -> None:
        job = self._make_job(monkeypatch)
        assert job["destination_database"] == "clonedb"
        assert job["destination_connection_id"] == "dst"
        assert job["in_place"] is False
