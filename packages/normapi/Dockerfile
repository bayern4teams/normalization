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
# ADR-023: the UI is built here and served by the API, so there is one port.
FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS builder

# PyICU (a normcore dependency) needs libicu-dev + pkg-config to build its
# sdist on Linux — see docs/adr/ADR-001-unicode-strategy.md. No equivalent
# Windows-wheel special-casing is needed here since this image only ever
# builds on Linux.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libicu-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Layer order is deliberate, for update pulls on the app machine: the
# heavy dependency layer's cache key is the lockfile plus the members'
# pyproject.toml files ONLY, so a code-only release reuses it entirely
# and downloads the few-MB code layer instead of ~1 GB of wheels. The
# first sync installs every third-party dependency without touching any
# member's source (`--no-install-workspace`: members install editable —
# verified, uv writes _editable_impl_*.pth pointing into the source tree
# — so no member is compiled here and none is needed yet). PyICU's sdist
# build needs the libicu-dev apt step above, which is a stable
# instruction, so its own layer caches too.
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/normapi/pyproject.toml packages/normapi/
COPY packages/normcore/pyproject.toml packages/normcore/
COPY packages/normdict/pyproject.toml packages/normdict/
COPY packages/normanalysis/pyproject.toml packages/normanalysis/
COPY packages/normexec/pyproject.toml packages/normexec/
COPY packages/normio/pyproject.toml packages/normio/
COPY packages/normalizers/pyproject.toml packages/normalizers/
COPY packages/normcli/pyproject.toml packages/normcli/

RUN uv sync --frozen --no-dev --no-install-workspace

# The second sync is the real one: it links the workspace members and
# no-ops on every already-installed dependency — this is the full install
# check, so a lockfile that cannot resolve the members fails the build.
COPY packages/ packages/
RUN uv sync --frozen --no-dev --package normapi

# A third sync then REMOVES the member installs again: the venv is frozen
# to exactly the third-party dependencies, byte-stable across code-only
# releases (uv's member install is editable — it rewrites .pth files and
# wheel stamps INSIDE .venv, so without this step the 800 MB venv layer
# changes digest on every build, verified with two local builds whose
# entire layer set differed on a one-line code change). The members are
# plain src/-layout packages with no console entry point and no
# importlib.metadata lookup at runtime (checked: env_fingerprint only
# reads third-party versions), so PYTHONPATH below is all they need.
# `--exact` matters: plain sync would re-add the members.
RUN uv sync --frozen --no-dev --no-install-workspace --exact

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        libicu72 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages /app/packages
COPY data/dictionaries /app/data/dictionaries
COPY --from=ui /ui/dist /app/ui/dist

ENV PATH="/app/.venv/bin:$PATH"
# The workspace members are not pip-installed in this image (see the
# builder's third sync); the source copied next to the venv is their
# import path. Explicit list, not a glob, so an image missing a member
# fails at import with that member's name, not silently without it.
ENV PYTHONPATH="/app/packages/normapi/src:/app/packages/normcore/src:/app/packages/normdict/src:/app/packages/normanalysis/src:/app/packages/normexec/src:/app/packages/normio/src:/app/packages/normalizers/src:/app/packages/normcli/src"
WORKDIR /app

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=20s \
    CMD curl -f http://localhost:8080/health || exit 1

# 0.0.0.0 is the container's own interface; compose.yaml publishes the port on
# NORM_BIND_ADDR only, so this does not expose the API on every host interface.
CMD ["uvicorn", "normapi.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
