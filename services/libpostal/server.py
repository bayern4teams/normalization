"""libpostal batch sidecar.

Thin FastAPI wrapper around pypostal's parser and expander. Exists so that:

- Windows dev machines never need MSys2/MinGW to build libpostal.
- The ~1.8-2.2GB resident model data is isolated to one container.
- The model data checksum is queryable and gets folded into every
  normalization run's env_id (see packages/normcore reproducibility design).

This process holds no state beyond the loaded libpostal model; normalization
policy (which expansions to trust, how to merge multiple candidate parses)
lives in packages/normalizers/address.py, not here.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from postal.expand import expand_address
from postal.parser import parse_address
from pydantic import BaseModel

app = FastAPI(title="libpostal-sidecar")

DATA_DIR = Path(os.environ.get("LIBPOSTAL_DATA_DIR", "/data/libpostal"))
_MODEL_SHA256_PATH = DATA_DIR / "MODEL_SHA256"


class ParseRequest(BaseModel):
    addresses: list[str]


class ParseComponent(BaseModel):
    label: str
    value: str


class ParseResult(BaseModel):
    input: str
    components: list[ParseComponent]


class ExpandRequest(BaseModel):
    addresses: list[str]


class ExpandResult(BaseModel):
    input: str
    expansions: list[str]


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_sha256": _model_sha256(),
    }


@app.get("/version")
def version() -> dict:
    return {"model_sha256": _model_sha256()}


@app.post("/parse", response_model=list[ParseResult])
def parse(req: ParseRequest) -> list[ParseResult]:
    results = []
    for address in req.addresses:
        parsed = parse_address(address)
        results.append(
            ParseResult(
                input=address,
                components=[ParseComponent(label=label, value=value) for value, label in parsed],
            )
        )
    return results


@app.post("/expand", response_model=list[ExpandResult])
def expand(req: ExpandRequest) -> list[ExpandResult]:
    results = []
    for address in req.addresses:
        expansions = expand_address(address)
        results.append(ExpandResult(input=address, expansions=list(expansions)))
    return results


def _model_sha256() -> str | None:
    if _MODEL_SHA256_PATH.exists():
        return _MODEL_SHA256_PATH.read_text().strip()
    return None
