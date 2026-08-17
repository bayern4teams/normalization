"""uvicorn entrypoint: `python -m uvicorn normapi.main:app` or via the
Dockerfile's CMD. Reads NORM_API_HOST/NORM_API_PORT for local `python -m
normapi.main` runs; the Docker image invokes uvicorn directly instead.
"""

from __future__ import annotations

import os

from normapi.app import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("NORM_API_HOST", "0.0.0.0"),  # intentional: container-facing API server
        port=int(os.environ.get("NORM_API_PORT", "8080")),
    )
