"""Unit tests for CustomDictionaryStore — Source.txt §59."""

from __future__ import annotations

from pathlib import Path

import pytest

from normdict import (
    BuiltinIdCollisionError,
    CustomDictionaryDeletedError,
    CustomDictionaryError,
    CustomDictionaryNotFoundError,
    CustomDictionaryStore,
    DictionaryLoader,
)


@pytest.fixture
def builtin_loader(tmp_path: Path) -> DictionaryLoader:
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    honorifics_dir = builtin_dir / "honorifics.common"
    honorifics_dir.mkdir()
    (honorifics_dir / "2026.08.json").write_text(
        '{"id": "honorifics.common", "version": "2026.08", "source": "s", '
        '"license": "l", "created_at": "2026-01-01T00:00:00Z", "entries": {}}',
        encoding="utf-8",
    )
    return DictionaryLoader(builtin_dir)


@pytest.fixture
def store(tmp_path: Path, builtin_loader: DictionaryLoader) -> CustomDictionaryStore:
    return CustomDictionaryStore(tmp_path / "custom", builtin_loader)


@pytest.mark.unit
class TestBuiltinCollisionGuard:
    def test_create_refuses_builtin_id(self, store: CustomDictionaryStore) -> None:
        with pytest.raises(BuiltinIdCollisionError):
            store.create(
                "honorifics.common",
                entries={},
                locale=None,
                source="x",
                license_="x",
                created_by="u",
            )

    def test_add_version_refuses_builtin_id(self, store: CustomDictionaryStore) -> None:
        with pytest.raises(BuiltinIdCollisionError):
            store.add_version("honorifics.common", entries={}, created_by="u")


@pytest.mark.unit
class TestCreateAndVersion:
    def test_create_produces_v1(self, store: CustomDictionaryStore) -> None:
        d = store.create(
            "aliases", entries={"a": "1"}, locale="en", source="s", license_="CC0", created_by="u"
        )
        assert d.version == "v1"
        assert d.entries == {"a": "1"}
        assert store.get_active_version("aliases") == "v1"

    def test_create_twice_rejected(self, store: CustomDictionaryStore) -> None:
        store.create("aliases", entries={}, locale=None, source="s", license_="l", created_by="u")
        with pytest.raises(CustomDictionaryError):
            store.create(
                "aliases", entries={}, locale=None, source="s", license_="l", created_by="u"
            )

    def test_add_version_replaces_entries_by_default(self, store: CustomDictionaryStore) -> None:
        store.create(
            "aliases", entries={"a": "1"}, locale=None, source="s", license_="l", created_by="u"
        )
        d2 = store.add_version("aliases", entries={"b": "2"}, created_by="u")
        assert d2.version == "v2"
        assert d2.entries == {"b": "2"}

    def test_add_version_merge_patches_entries(self, store: CustomDictionaryStore) -> None:
        store.create(
            "aliases", entries={"a": "1"}, locale=None, source="s", license_="l", created_by="u"
        )
        d2 = store.add_version("aliases", entries={"b": "2"}, created_by="u", merge=True)
        assert d2.entries == {"a": "1", "b": "2"}

    def test_add_version_merge_deletes_key_on_none(self, store: CustomDictionaryStore) -> None:
        store.create(
            "aliases", entries={"a": "1"}, locale=None, source="s", license_="l", created_by="u"
        )
        d2 = store.add_version("aliases", entries={"a": None}, created_by="u", merge=True)
        assert d2.entries == {}

    def test_versions_never_overwritten(self, store: CustomDictionaryStore) -> None:
        store.create(
            "aliases", entries={"a": "1"}, locale=None, source="s", license_="l", created_by="u"
        )
        store.add_version("aliases", entries={"b": "2"}, created_by="u")
        v1 = store.load("aliases", "v1")
        assert v1.entries == {"a": "1"}


@pytest.mark.unit
class TestRollback:
    def test_rollback_reactivates_prior_version(self, store: CustomDictionaryStore) -> None:
        store.create(
            "aliases", entries={"a": "1"}, locale=None, source="s", license_="l", created_by="u"
        )
        store.add_version("aliases", entries={"b": "2"}, created_by="u")
        rolled = store.rollback("aliases", "v1", by="bob")
        assert rolled.entries == {"a": "1"}
        assert store.get_active_version("aliases") == "v1"

    def test_rollback_does_not_delete_newer_version(self, store: CustomDictionaryStore) -> None:
        store.create(
            "aliases", entries={"a": "1"}, locale=None, source="s", license_="l", created_by="u"
        )
        store.add_version("aliases", entries={"b": "2"}, created_by="u")
        store.rollback("aliases", "v1", by="bob")
        # rolling forward again must still work — v2 was never deleted
        forward = store.rollback("aliases", "v2", by="bob")
        assert forward.entries == {"b": "2"}

    def test_rollback_unknown_version_raises(self, store: CustomDictionaryStore) -> None:
        store.create("aliases", entries={}, locale=None, source="s", license_="l", created_by="u")
        with pytest.raises(CustomDictionaryNotFoundError):
            store.rollback("aliases", "v99", by="bob")


@pytest.mark.unit
class TestDelete:
    def test_delete_blocks_further_writes(self, store: CustomDictionaryStore) -> None:
        store.create("aliases", entries={}, locale=None, source="s", license_="l", created_by="u")
        store.delete("aliases", by="bob")
        assert store.is_deleted("aliases") is True
        with pytest.raises(CustomDictionaryDeletedError):
            store.add_version("aliases", entries={"x": "y"}, created_by="u")
        with pytest.raises(CustomDictionaryDeletedError):
            store.rollback("aliases", "v1", by="bob")

    def test_delete_does_not_physically_remove_versions(self, store: CustomDictionaryStore) -> None:
        store.create(
            "aliases", entries={"a": "1"}, locale=None, source="s", license_="l", created_by="u"
        )
        store.delete("aliases", by="bob")
        # audit trail preserved on disk — direct load by version still works
        assert store.load("aliases", "v1").entries == {"a": "1"}


@pytest.mark.unit
class TestListing:
    def test_list_custom_ids(self, store: CustomDictionaryStore) -> None:
        store.create("aliases", entries={}, locale=None, source="s", license_="l", created_by="u")
        store.create("other", entries={}, locale=None, source="s", license_="l", created_by="u")
        assert store.list_custom_ids() == ["aliases", "other"]

    def test_list_versions(self, store: CustomDictionaryStore) -> None:
        store.create("aliases", entries={}, locale=None, source="s", license_="l", created_by="u")
        store.add_version("aliases", entries={"a": "1"}, created_by="u")
        assert store.list_versions("aliases") == ["v1", "v2"]

    def test_unknown_dictionary_raises_not_found(self, store: CustomDictionaryStore) -> None:
        with pytest.raises(CustomDictionaryNotFoundError):
            store.load("nonexistent")
