"""User custom dictionary CRUD/versioning/rollback — Source.txt §59.

Built-in dictionaries (loaded read-only by `DictionaryLoader`) are never
touched by this module — `CustomDictionaryStore` writes to a completely
separate root directory, and `create()` refuses outright to create a
custom dictionary whose id collides with a built-in one (checked against
a real, live `DictionaryLoader` instance at write time, not just by
convention/naming discipline).

On-disk layout mirrors `DictionaryLoader`'s own convention so the two
stay trivially reconcilable: `{root_dir}/{id}/{version}.json`, plus one
`{root_dir}/{id}/_state.json` recording the currently-active version and
whether the dictionary has been deleted. Versions are immutable once
written (§59: "Version") — `add_version()` always writes a new file,
never rewrites an existing one. `rollback()` only ever moves the active
pointer backward to a version that already exists on disk; it does not
delete newer versions, so rolling forward again after a rollback is
always possible (mirrors the "never overwrite" discipline the profile
store already applies to `NormalizationProfile` versions).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import blake3

from normdict.models import Dictionary

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normdict.loader import DictionaryLoader


class CustomDictionaryError(Exception):
    pass


class BuiltinIdCollisionError(CustomDictionaryError):
    """Raised when a caller tries to create/version a custom dictionary
    under an id already owned by a built-in dictionary — §59's "never
    mutate built-in dictionaries" enforced at the write boundary."""


class CustomDictionaryNotFoundError(CustomDictionaryError, LookupError):
    pass


class CustomDictionaryDeletedError(CustomDictionaryError):
    pass


class CustomDictionaryStore:
    def __init__(self, root_dir: str | Path, builtin_loader: DictionaryLoader) -> None:
        self._root_dir = Path(root_dir)
        self._builtin_loader = builtin_loader

    # --- internal state file -------------------------------------------

    def _dict_dir(self, dictionary_id: str) -> Path:
        return self._root_dir / dictionary_id

    def _state_path(self, dictionary_id: str) -> Path:
        return self._dict_dir(dictionary_id) / "_state.json"

    def _read_state(self, dictionary_id: str) -> dict[str, Any]:
        path = self._state_path(dictionary_id)
        if not path.exists():
            msg = f"No such custom dictionary: {dictionary_id!r}"
            raise CustomDictionaryNotFoundError(msg)
        state: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return state

    def _write_state(self, dictionary_id: str, state: dict[str, Any]) -> None:
        self._state_path(dictionary_id).write_text(
            json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _assert_no_builtin_collision(self, dictionary_id: str) -> None:
        if dictionary_id in self._builtin_loader.list_dictionary_ids():
            msg = (
                f"{dictionary_id!r} is a built-in dictionary id — custom dictionaries "
                "must never mutate or shadow a built-in dictionary (Source.txt §59)"
            )
            raise BuiltinIdCollisionError(msg)

    # --- create / list ----------------------------------------------------

    def list_custom_ids(self) -> Sequence[str]:
        if not self._root_dir.exists():
            return []
        return sorted(
            p.name for p in self._root_dir.iterdir() if p.is_dir() and (p / "_state.json").exists()
        )

    def exists(self, dictionary_id: str) -> bool:
        return self._state_path(dictionary_id).exists()

    def create(
        self,
        dictionary_id: str,
        *,
        entries: dict[str, Any],
        locale: str | None,
        source: str,
        license_: str,
        created_by: str,
    ) -> Dictionary:
        self._assert_no_builtin_collision(dictionary_id)
        if self.exists(dictionary_id):
            msg = (
                f"Custom dictionary {dictionary_id!r} already exists — use add_version() "
                "to change it, not create()"
            )
            raise CustomDictionaryError(msg)

        dictionary = self._write_version(
            dictionary_id,
            version="v1",
            entries=entries,
            locale=locale,
            source=source,
            license_=license_,
        )
        self._write_state(
            dictionary_id,
            {
                "active_version": "v1",
                "versions": ["v1"],
                "deleted": False,
                "created_by": created_by,
                "history": [
                    {
                        "action": "create",
                        "version": "v1",
                        "by": created_by,
                        "at": _now(),
                    }
                ],
            },
        )
        return dictionary

    def add_version(
        self,
        dictionary_id: str,
        *,
        entries: dict[str, Any],
        locale: str | None = None,
        source: str | None = None,
        license_: str | None = None,
        created_by: str,
        merge: bool = False,
    ) -> Dictionary:
        """`merge=True` patches the active version's entries (add/edit/
        delete individual keys — pass a key with value `None` to delete
        it); `merge=False` (default) replaces the entries outright."""
        self._assert_no_builtin_collision(dictionary_id)
        state = self._read_state(dictionary_id)
        if state["deleted"]:
            msg = f"Custom dictionary {dictionary_id!r} was deleted; cannot add a version to it"
            raise CustomDictionaryDeletedError(msg)

        current = self.load(dictionary_id)
        next_version = f"v{len(state['versions']) + 1}"

        if merge:
            merged_entries = dict(current.entries)
            for key, value in entries.items():
                if value is None:
                    merged_entries.pop(key, None)
                else:
                    merged_entries[key] = value
            resolved_entries = merged_entries
        else:
            resolved_entries = entries

        dictionary = self._write_version(
            dictionary_id,
            version=next_version,
            entries=resolved_entries,
            locale=locale if locale is not None else current.locale,
            source=source if source is not None else current.source,
            license_=license_ if license_ is not None else current.license,
        )

        state["active_version"] = next_version
        state["versions"].append(next_version)
        state["history"].append(
            {"action": "add_version", "version": next_version, "by": created_by, "at": _now()}
        )
        self._write_state(dictionary_id, state)
        return dictionary

    def rollback(self, dictionary_id: str, target_version: str, *, by: str) -> Dictionary:
        state = self._read_state(dictionary_id)
        if state["deleted"]:
            msg = f"Custom dictionary {dictionary_id!r} was deleted; cannot roll it back"
            raise CustomDictionaryDeletedError(msg)
        if target_version not in state["versions"]:
            msg = f"{dictionary_id!r} has no version {target_version!r} to roll back to"
            raise CustomDictionaryNotFoundError(msg)

        state["active_version"] = target_version
        state["history"].append(
            {"action": "rollback", "version": target_version, "by": by, "at": _now()}
        )
        self._write_state(dictionary_id, state)
        return self.load(dictionary_id, target_version)

    def delete(self, dictionary_id: str, *, by: str) -> None:
        """Tombstones the custom dictionary — refuses further reads/writes
        via this store, but does not physically remove version files
        (audit trail, consistent with never-overwrite elsewhere in this
        codebase)."""
        state = self._read_state(dictionary_id)
        state["deleted"] = True
        state["history"].append({"action": "delete", "version": None, "by": by, "at": _now()})
        self._write_state(dictionary_id, state)

    def list_versions(self, dictionary_id: str) -> Sequence[str]:
        return list(self._read_state(dictionary_id)["versions"])

    def get_active_version(self, dictionary_id: str) -> str:
        state = self._read_state(dictionary_id)
        if state["deleted"]:
            msg = f"Custom dictionary {dictionary_id!r} was deleted"
            raise CustomDictionaryDeletedError(msg)
        active: str = state["active_version"]
        return active

    def is_deleted(self, dictionary_id: str) -> bool:
        return bool(self._read_state(dictionary_id)["deleted"])

    def load(self, dictionary_id: str, version: str | None = None) -> Dictionary:
        state = self._read_state(dictionary_id)
        resolved_version = version if version is not None else state["active_version"]
        path = self._dict_dir(dictionary_id) / f"{resolved_version}.json"
        if not path.exists():
            msg = f"No such version {resolved_version!r} for custom dictionary {dictionary_id!r}"
            raise CustomDictionaryNotFoundError(msg)

        raw_bytes = path.read_bytes()
        content_hash = blake3.blake3(raw_bytes).hexdigest()
        payload = json.loads(raw_bytes)
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

    def _write_version(
        self,
        dictionary_id: str,
        *,
        version: str,
        entries: dict[str, Any],
        locale: str | None,
        source: str,
        license_: str,
    ) -> Dictionary:
        dict_dir = self._dict_dir(dictionary_id)
        dict_dir.mkdir(parents=True, exist_ok=True)
        created_at = _now()
        payload = {
            "id": dictionary_id,
            "version": version,
            "locale": locale,
            "source": source,
            "license": license_,
            "created_at": created_at,
            "entries": entries,
        }
        raw_bytes = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
        (dict_dir / f"{version}.json").write_bytes(raw_bytes)
        content_hash = blake3.blake3(raw_bytes).hexdigest()
        return Dictionary(
            id=dictionary_id,
            version=version,
            locale=locale,
            source=source,
            license=license_,
            created_at=created_at,
            entries=entries,
            content_hash=content_hash,
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()
