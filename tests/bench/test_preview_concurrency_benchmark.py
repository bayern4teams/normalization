"""D37: `POST /normalization/preview` throughput must not fall when callers
run at the same time. Measured on `main` 8f3b63c with the round 3 benchmark's
request mix: 263 req/s at 1 user, 42 at 4, 27.5 at 16.

A real uvicorn process and a fixed request mix, replayed at 1 and 16 users,
RUNS times each. The 16-user median must reach 95 % of the 1-user median
(owner, 2026-11-19: "Allow 5% tolerance"). The first criterion, "not below by
more than the noise", failed after the fix by 3.6 % against a 1.1 % spread: one
thread for the work still shares the GIL with the event loop.
"""

from __future__ import annotations

import asyncio
import os
import socket
import statistics
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.bench

RUNS = 3
TOLERATED = 0.95  # owner, 2026-11-19: "Allow 5% tolerance"
REQUESTS = 600

# Shaped like the round 3 mix: mostly COUNTRY, a few dates that miss the ISO
# and EDTF shortcuts and reach dateparser (the slow path), one of most others.
_MIX: list[tuple[str, str]] = [
    *[("COUNTRY", v) for v in ("Germany", "uk", "FR", "Espana", "Korea", "Nowhere")] * 13,
    ("DATE", "2024-02-30"),
    ("DATE", "1990"),
    ("DATE", "March 2024"),
    ("DATE", "5 March 2024"),
    ("DATE", "2024-03-05"),
    ("LANGUAGE", "German"),
    ("LANGUAGE", "fr"),
    ("PHONE", "+44 20 7946 0958"),
    ("CURRENCY", "EUR"),
    ("EMAIL", "A.Person@Example.com"),
    ("URL", "https://example.com/a"),
    ("NUMERIC", "1,234.5"),
    ("BOOLEAN", "yes"),
    ("UUID", "123e4567-e89b-12d3-a456-426614174000"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "normapi.main:app", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            pytest.fail("uvicorn did not answer /health within 120 s")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=30)


async def _level(url: str, users: int) -> float:
    sent = 0

    async def user(client: httpx.AsyncClient) -> None:
        nonlocal sent
        while sent < REQUESTS:
            semantic_type, value = _MIX[sent % len(_MIX)]
            sent += 1
            body = {"field_name": "f", "semantic_type": semantic_type, "values": [value]}
            response = await client.post(f"{url}/normalization/preview", json=body)
            assert response.status_code == 200, response.text

    limits = httpx.Limits(max_connections=users)
    async with httpx.AsyncClient(timeout=120, limits=limits) as client:
        start = time.perf_counter()
        await asyncio.gather(*(user(client) for _ in range(users)))
        return REQUESTS / (time.perf_counter() - start)


def test_throughput_at_16_users_holds_against_1_user(base_url: str) -> None:
    asyncio.run(_level(base_url, 1))  # warm-up: dateparser loads its locales once
    one = [asyncio.run(_level(base_url, 1)) for _ in range(RUNS)]
    sixteen = [asyncio.run(_level(base_url, 16)) for _ in range(RUNS)]
    print(f"req/s 1 user {[round(x) for x in one]}, 16 users {[round(x) for x in sixteen]}")
    assert statistics.median(sixteen) >= TOLERATED * statistics.median(one), (one, sixteen)
