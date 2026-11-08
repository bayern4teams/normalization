"""D16 (R23): a raw value appears only in the direct answer to the caller who
sent it. Each test plants a value and reads one route or log path."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.clone_executor import _ColumnStats, _job_error_text, _report_column_findings
from normcore.enums import FieldSemanticType
from tests.unit.test_adjudication_acceptance import RAW_DATE, _Env, _rows

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_PLANTED = "Zebulon Quartzfield"
_CLIENT = ("127.0.0.1", 50000)
_ROUTE = "/normalization/suggest-profile"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Env:
    monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())
    return _Env(tmp_path)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), client=_CLIENT)


def _job_id(env: _Env) -> str:
    return env.run([_rows([{"d": RAW_DATE}])], {"d": "DATE"})[0]


def _run_with(client: TestClient, value: str) -> str:
    profile = client.post(
        "/normalization/profiles", json={"name": "p", "field_configs": [], "created_by": "u"}
    ).json()
    run = client.post(
        f"/normalization/runs?profile_id={profile['id']}&source_snapshot=s",
        json={"field_name": "name", "semantic_type": "PERSON_NAME", "values": [value]},
    ).json()
    return str(run["id"])


def _assert_masked(text: str) -> None:
    assert _PLANTED not in text
    assert "Zebulon" not in text
    assert "Quartzfield" not in text


def test_run_values_are_masked(client: TestClient) -> None:
    response = client.get(f"/normalization/runs/{_run_with(client, _PLANTED)}/values")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["result"]["normalization_status"]
    _assert_masked(response.text)


@pytest.mark.parametrize(
    "error",
    [
        f"value {_PLANTED!r} is not a number; stored as NULL",
        f"value {_PLANTED!r} means missing; stored as NULL",
        f"{_PLANTED} is not valid",
    ],
)
def test_clone_job_row_error_is_masked(env: _Env, error: str) -> None:
    job_id = _job_id(env)
    env.persistence.save_clone_job_errors(
        job_id,
        [{"row_index": 7, "table_name": "t", "field": "f", "original": _PLANTED, "error": error}],
    )
    response = env.client.get(f"/normalization/clone-jobs/{job_id}/errors")
    assert response.status_code == 200
    assert any(e["record_ref"] == "7" for e in response.json())
    _assert_masked(response.text)


def test_clone_job_date_bound_error_is_masked(env: _Env) -> None:
    job_id = _job_id(env)
    env.persistence.save_clone_job_errors(
        job_id,
        [
            {
                "row_index": 7,
                "table_name": "t",
                "field": "f",
                "original": "12/11/1989",
                "error": "date bound 1989-11-12 is outside 1900-01-01..2100-01-01; stored as NULL",
            }
        ],
    )
    response = env.client.get(f"/normalization/clone-jobs/{job_id}/errors")
    assert "stored as NULL" in response.text
    assert "1989-11-12" not in response.text


def test_clone_job_column_finding_examples_are_masked(env: _Env) -> None:
    job_id = _job_id(env)
    mistyped = _ColumnStats(total=1000)
    for _ in range(1000):
        mistyped.record_invalid(_PLANTED)
    unstable = _ColumnStats(total=1000, checked_stable=50)
    unstable.record_unstable(_PLANTED, "Quartzfield, Zebulon")
    _report_column_findings(
        env.persistence,
        job_id,
        "t",
        stats={"country": mistyped, "name": unstable},
        semantic_types={
            "country": FieldSemanticType.COUNTRY,
            "name": FieldSemanticType.COMPANY_NAME,
        },
        ceiling=None,
    )
    response = env.client.get(f"/normalization/clone-jobs/{job_id}/errors")
    assert "not a COUNTRY" in response.text
    assert "not converging" in response.text
    _assert_masked(response.text)


def test_failed_job_error_is_masked(env: _Env) -> None:
    job_id = _job_id(env)
    failure = sa.exc.IntegrityError("INSERT", {"v": _PLANTED}, ValueError(_PLANTED))
    job = env.persistence.get_clone_job(job_id)
    assert job is not None
    job["error"] = _job_error_text(failure)
    env.persistence.save_clone_job(job_id, job)
    response = env.client.get(f"/normalization/clone-jobs/{job_id}")
    assert "ValueError" in response.json()["error"]
    _assert_masked(response.text)


def test_failed_job_keeps_a_message_that_cannot_hold_values() -> None:
    assert _job_error_text(RuntimeError("disk full")) == "disk full"


def test_access_log_has_no_query_string(client: TestClient) -> None:
    assert client.app is not None  # create_app installs the filter
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", f"{_ROUTE}?sample_value={_PLANTED}", "1.1", 200),
        None,
    )
    assert logging.getLogger("uvicorn.access").filter(record)
    assert _ROUTE in record.getMessage()
    _assert_masked(record.getMessage())


def test_preview_may_echo_its_own_input(client: TestClient) -> None:
    response = client.post(
        "/normalization/preview",
        json={"field_name": "f", "semantic_type": "PERSON_NAME", "values": [_PLANTED]},
    )
    assert response.status_code == 200
    assert _PLANTED in response.text
