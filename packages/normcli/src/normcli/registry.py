"""Builds the same 20-normalizer registry and process env_id that
`normapi.app.create_app()` builds (`packages/normapi/src/normapi/app.py:229-264`),
so `normcli run` normalizes with the real normalizer set rather than a
CLI-only subset — its whole purpose is proving ADR-014 determinism for
what actually runs in production.

Duplicated here rather than imported from `normapi` deliberately:
`normapi` depends on FastAPI/uvicorn/psycopg for the HTTP server, none of
which a local CLI process needs to pull in just to build a normalizer
registry. If this list drifts out of sync with `app.py`'s, both are
short and reviewable side by side; a future Phase 3 process-pool worker
that needs the same construction from *inside* normapi's own process can
still extract a shared helper there without normcli taking on normapi's
dependency weight.
"""

from __future__ import annotations

import os
from pathlib import Path

from normalizers.address import AddressNormalizer, LibpostalClient
from normalizers.boolean import BooleanNormalizer
from normalizers.company import CompanyNormalizer
from normalizers.country import CountryNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.generic_text import GenericTextNormalizer
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.name import NameNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normalizers.postcode import PostcodeNormalizer
from normalizers.script import ScriptNormalizer
from normalizers.unit import UnitNormalizer
from normalizers.url import URLNormalizer
from normexec.env_fingerprint import compute_env_id, gather

from normcore import NormalizerRegistry
from normdict import DictionaryLoader

# Same env var app.py reads (compose.yaml sets it to /app/data/dictionaries
# in-container); same relative-path default for local `uv run` invocations.
DEFAULT_DICTIONARIES_DIR = Path(os.environ.get("NORM_DICTIONARIES_DIR", "data/dictionaries"))
DEFAULT_LIBPOSTAL_URL = os.environ.get("NORM_LIBPOSTAL_URL", "http://localhost:8081")

# Matches app.py's _ENV_ID_PROFILE_VERSION_PLACEHOLDER exactly (see that
# constant's own comment for why) — keeping it identical means a CLI run
# and a live server run computed on the same machine/dependencies get the
# same env_id, which is what makes a `normcli run` a meaningful stand-in
# for "what the real server would have produced."
_ENV_ID_PROFILE_VERSION_PLACEHOLDER = "unversioned"


def build_normalizer_registry(
    dictionaries_dir: Path, libpostal_client: LibpostalClient
) -> NormalizerRegistry:
    loader = DictionaryLoader(dictionaries_dir)
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(GenericTextNormalizer(loader))
    registry.register(NameNormalizer(loader))
    registry.register(CompanyNormalizer(loader))
    registry.register(PhoneNormalizer())
    registry.register(EmailNormalizer())
    registry.register(AddressNormalizer(libpostal_client))
    registry.register(PostcodeNormalizer())
    registry.register(DateNormalizer())
    registry.register(CountryNormalizer())
    registry.register(LanguageNormalizer())
    registry.register(ScriptNormalizer())
    registry.register(IdentifierNormalizer())
    registry.register(UuidNormalizer())
    registry.register(NumericNormalizer())
    registry.register(CurrencyNormalizer())
    registry.register(UnitNormalizer())
    registry.register(BooleanNormalizer())
    registry.register(URLNormalizer())
    return registry


def compute_process_env_id(*, dictionaries_dir: Path, libpostal_client: LibpostalClient) -> str:
    """`version()` never raises even when the libpostal sidecar isn't up
    (see `LibpostalClient.version`'s own docstring) — env_id is simply
    computed with `libpostal_model_sha256=None` in that case, same
    graceful degradation `app.py` relies on."""
    inputs = gather(
        libpostal_model_sha256=libpostal_client.version(),
        profile_version=_ENV_ID_PROFILE_VERSION_PLACEHOLDER,
        dictionaries_dir=dictionaries_dir,
    )
    return compute_env_id(inputs)
