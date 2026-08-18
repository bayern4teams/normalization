# Built with root context (see compose.yaml: `context: ., dockerfile:
# packages/normapi/Dockerfile`) since the workspace's uv.lock and every
# workspace member package live above packages/normapi/ in the tree.
#
# Pinned to the `-bookworm` suffix (not the floating `python:3.12-slim`,
# which tracks whatever Debian release is currently "stable" and silently
# rolled from bookworm to trixie at some point after this file was
# written) — the runtime stage below pins the ICU runtime package to its
# bookworm SONAME (`libicu72`), and an unpinned base image drifting out
# from under that pin breaks the build with "Unable to locate package
# libicu72" (a real failure hit while re-verifying M7's Docker-based e2e
# CI job, not a hypothetical). Bump both the suffix and `libicu72` together,
# deliberately, when moving to a newer Debian release.
FROM python:3.12-slim-bookworm AS builder

# PyICU (a normcore dependency) needs libicu-dev + pkg-config to build its
# sdist on Linux — see docs/adr/ADR-001-unicode-strategy.md. No equivalent
# Windows-wheel special-casing is needed here since this image only ever
# builds on Linux.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libicu-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/ packages/

RUN uv sync --frozen --no-dev --package normapi

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        libicu72 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages /app/packages
COPY data/dictionaries /app/data/dictionaries

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=20s \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "normapi.main:app", "--host", "0.0.0.0", "--port", "8080"]
