"""Read-only dictionary loader — Source.txt §58 (read path only; §59's
full CRUD/versioning/custom-overlay subsystem lands in M6).

Dictionaries live as immutable JSON files under `root_dir`, one file per
`{id, version}` pair, discovered by filename convention:
`{root_dir}/{id}/{version}.json`. This mirrors exactly what
scripts/env_fingerprint.py's `collect_dictionary_hashes` already assumes
when it globs `data/dictionaries/**/*.json` — both pieces of code must
agree on the on-disk shape, verified by tests/unit/test_normdict.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import blake3

from normdict.models import Dictionary

if TYPE_CHECKING:
    from collections.abc import Sequence


class DictionaryNotFoundError(LookupError):
    pass


class DictionaryLoader:
    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir)

    def list_dictionary_ids(self) -> Sequence[str]:
        if not self._root_dir.exists():
            return []
        return sorted(p.name for p in self._root_dir.iterdir() if p.is_dir())

    def list_versions(self, dictionary_id: str) -> Sequence[str]:
        dict_dir = self._root_dir / dictionary_id
        if not dict_dir.exists():
            return []
        return sorted(p.stem for p in dict_dir.glob("*.json"))

    def load(self, dictionary_id: str, version: str | None = None) -> Dictionary:
        """`version=None` loads the lexicographically latest version file
        present — callers needing a specific pinned version (the normal
        case in a profile's `dictionary_refs`) must pass it explicitly.

        Lexicographic "latest" is a known limitation for non-zero-padded
        numeric version schemes (e.g. "v10" sorts before "v2"); date-based
        versions like "2026.08" sort correctly. Full semantic versioning
        support is in scope for M6's dictionary management subsystem, not
        this minimal M1 read path.
        """
        versions = self.list_versions(dictionary_id)
        if not versions:
            msg = f"No dictionary found for id={dictionary_id!r}"
            raise DictionaryNotFoundError(msg)

        resolved_version = version if version is not None else versions[-1]
        path = self._root_dir / dictionary_id / f"{resolved_version}.json"
        if not path.exists():
            msg = f"No such version {resolved_version!r} for dictionary {dictionary_id!r}"
            raise DictionaryNotFoundError(msg)

        raw_bytes = path.read_bytes()
        content_hash = blake3.blake3(raw_bytes).hexdigest()
        payload = json.loads(raw_bytes)

        if payload["id"] != dictionary_id or payload["version"] != resolved_version:
            msg = (
                f"Dictionary file {path} declares id={payload['id']!r} "
                f"version={payload['version']!r}, but was loaded as "
                f"id={dictionary_id!r} version={resolved_version!r} "
                f"(path and content must agree — likely a copy-paste error)"
            )
            raise ValueError(msg)

        return Dictionary(
            id=payload["id"],
            version=payload["version"],
            locale=payload.get("locale"),
            source=payload["source"],
            license=payload["license"],
            created_at=payload["created_at"],
            entries=payload.get("entries", {}),
            content_hash=content_hash,
        )
