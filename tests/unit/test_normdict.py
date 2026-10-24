"""Proves normdict's read-only loader against both the real seeded
dictionary (data/dictionaries/honorifics.common/) and synthetic fixtures,
and — critically — that its content_hash/key format actually agrees with
scripts/env_fingerprint.py's independently-implemented
`collect_dictionary_hashes`, since both must produce the same
`{id}@{version}` key for env_id to correctly reflect dictionary versions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from normdict import Dictionary, DictionaryLoader, DictionaryNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
from env_fingerprint import collect_dictionary_hashes  # noqa: E402


@pytest.mark.unit
def test_loads_the_real_seeded_honorifics_dictionary() -> None:
    loader = DictionaryLoader(REPO_ROOT / "data" / "dictionaries")
    dictionary = loader.load("honorifics.common", "2026.08")

    assert dictionary.id == "honorifics.common"
    assert dictionary.version == "2026.08"
    assert dictionary.locale == "en"
    assert dictionary.entries["Mr."] == "Mr"
    assert dictionary.entries["Doctor"] == "Dr"
    assert dictionary.key == "honorifics.common@2026.08"


@pytest.mark.unit
def test_content_hash_agrees_with_env_fingerprint_collect_dictionary_hashes() -> None:
    """The two pieces of code (normdict.DictionaryLoader and
    scripts/env_fingerprint.py) are maintained independently but MUST
    agree on the {id}@{version} -> hash mapping, since env_id's
    reproducibility guarantee depends on it. This test would catch either
    one silently drifting from the other.
    """
    dict_dir = REPO_ROOT / "data" / "dictionaries"
    loader = DictionaryLoader(dict_dir)
    dictionary = loader.load("honorifics.common", "2026.08")

    fingerprint_hashes = collect_dictionary_hashes(dict_dir)
    assert dictionary.key in fingerprint_hashes
    assert fingerprint_hashes[dictionary.key] == dictionary.content_hash


@pytest.fixture
def dict_root(tmp_path: Path) -> Path:
    dict_dir = tmp_path / "test.dict"
    dict_dir.mkdir(parents=True)
    payload = {
        "id": "test.dict",
        "version": "v1",
        "locale": None,
        "source": "synthetic",
        "license": "CC0-1.0",
        "created_at": "2026-01-01T00:00:00Z",
        "entries": {"a": 1, "b": 2},
    }
    (dict_dir / "v1.json").write_text(json.dumps(payload), encoding="utf-8")

    payload_v2 = {**payload, "version": "v2", "entries": {"a": 1, "b": 2, "c": 3}}
    (dict_dir / "v2.json").write_text(json.dumps(payload_v2), encoding="utf-8")
    return tmp_path


@pytest.mark.unit
def test_list_dictionary_ids_and_versions(dict_root: Path) -> None:
    loader = DictionaryLoader(dict_root)
    assert loader.list_dictionary_ids() == ["test.dict"]
    assert loader.list_versions("test.dict") == ["v1", "v2"]


@pytest.mark.unit
def test_load_specific_version_vs_latest(dict_root: Path) -> None:
    loader = DictionaryLoader(dict_root)
    v1 = loader.load("test.dict", "v1")
    assert len(v1.entries) == 2

    latest = loader.load("test.dict")  # no version -> latest
    assert latest.version == "v2"
    assert len(latest.entries) == 3


@pytest.mark.unit
def test_raises_on_unknown_dictionary_id(dict_root: Path) -> None:
    loader = DictionaryLoader(dict_root)
    with pytest.raises(DictionaryNotFoundError):
        loader.load("does.not.exist")


@pytest.mark.unit
def test_raises_on_unknown_version(dict_root: Path) -> None:
    loader = DictionaryLoader(dict_root)
    with pytest.raises(DictionaryNotFoundError):
        loader.load("test.dict", "v999")


@pytest.mark.unit
def test_raises_on_path_payload_mismatch(tmp_path: Path) -> None:
    dict_dir = tmp_path / "declared.id"
    dict_dir.mkdir(parents=True)
    payload = {
        "id": "wrong.id",  # deliberately mismatched with the directory name
        "version": "v1",
        "source": "synthetic",
        "license": "CC0-1.0",
        "created_at": "2026-01-01T00:00:00Z",
        "entries": {},
    }
    (dict_dir / "v1.json").write_text(json.dumps(payload), encoding="utf-8")

    loader = DictionaryLoader(tmp_path)
    with pytest.raises(ValueError, match="likely a copy-paste error"):
        loader.load("declared.id", "v1")


@pytest.mark.unit
def test_two_dictionaries_with_identical_entries_differ_by_content_hash(dict_root: Path) -> None:
    """A sanity check that content_hash actually reflects file content
    (different entries -> different hash), not a constant/placeholder."""
    loader = DictionaryLoader(dict_root)
    v1 = loader.load("test.dict", "v1")
    v2 = loader.load("test.dict", "v2")
    assert v1.content_hash != v2.content_hash


@pytest.mark.unit
def test_dictionary_model_is_frozen() -> None:
    dictionary = Dictionary(
        id="x",
        version="v1",
        source="s",
        license="l",
        created_at="2026-01-01T00:00:00Z",
        entries={},
        content_hash="h",
    )
    with pytest.raises(Exception, match=r"frozen|Instance is frozen"):
        dictionary.version = "v2"  # type: ignore[misc]
