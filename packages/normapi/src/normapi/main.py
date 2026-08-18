"""uvicorn entrypoint: `python -m uvicorn normapi.main:app` or via the
Dockerfile's CMD. Reads NORM_API_HOST/NORM_API_PORT for local `python -m
normapi.main` runs; the Docker image invokes uvicorn directly instead.
"""

from __future__ import annotations

import os

# Must precede any pyarrow import anywhere in this process — see
# docs/adr/ADR-001-unicode-strategy.md's DLL-load-order addendum and
# normalizers/__init__.py, which applies the same guard for library
# consumers. Explicit here too since this file is the actual production
# server entrypoint (`uvicorn normapi.main:app`), not just a library import.
import icu  # noqa: F401

from normapi.app import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("NORM_API_HOST", "0.0.0.0"),  # intentional: container-facing API server
        port=int(os.environ.get("NORM_API_PORT", "8080")),
    )
