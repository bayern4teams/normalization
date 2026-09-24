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

# `__mp_main__` means a multiprocessing worker is re-importing this module.
# Both "spawn" and "forkserver" re-execute the parent's __main__ module in
# every child (verified, not assumed — `set_forkserver_preload([])` does
# not prevent it), so when the server is started as `python -m
# normapi.main` this line would otherwise build a second FastAPI app,
# Postgres pool and DuckDB cache inside each clone-job worker. Measured
# per-worker cost is ~180MB, and the DuckDB cache would additionally fail
# on a file lock already held by the parent.
#
# Under the Dockerfile's `uvicorn normapi.main:app`, __name__ here is
# "normapi.main" — an ordinary import — so this guard is inert in
# production and only protects the documented local-run path above.
app = None if __name__ == "__mp_main__" else create_app()

if __name__ == "__main__":
    import uvicorn

    # `app` is only None under __mp_main__ (a multiprocessing re-import),
    # which never reaches __main__ — asserted so the type is honest.
    assert app is not None
    uvicorn.run(
        app,
        host=os.environ.get("NORM_API_HOST", "0.0.0.0"),  # intentional: container-facing API server
        port=int(os.environ.get("NORM_API_PORT", "8080")),
    )
