"""Dictionary domain model — Source.txt §58.

Every dictionary is: id, version, locale, source, license, entries,
created_at. Dictionaries are immutable files on disk, one JSON file per
`{id, version}` pair — the full CRUD/versioning/rollback/custom-overlay
subsystem (§59) lands in M6; this is the read-only interface M3's
CompanyNormalizer and others depend on starting now.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Dictionary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    locale: str | None = None
    source: str
    license: str
    created_at: str  # ISO 8601
    entries: dict[str, Any] = Field(default_factory=dict)
    content_hash: str  # blake3 of the raw file bytes, computed at load time — feeds env_id

    @property
    def key(self) -> str:
        """Matches the `{id}@{version}` format scripts/env_fingerprint.py
        uses when hashing dictionaries into env_id — keeping these two
        independently-implemented pieces of code producing the same key
        format is asserted by tests/unit/test_normdict.py, not just
        assumed.
        """
        return f"{self.id}@{self.version}"
