"""Proves scripts/env_fingerprint.py's core promise (docs/adr/ADR-014):
same inputs -> same env_id (stability), any one input changed -> different
env_id (sensitivity). This is what makes env_id trustworthy as the basis
for reproducibility comparisons across runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from env_fingerprint import EnvFingerprintInputs, compute_env_id


def _baseline() -> EnvFingerprintInputs:
    return EnvFingerprintInputs(
        packages={"phonenumbers": "8.13.0", "ftfy": "6.3.1"},
        icu_version="78.3",
        unicode_version="17.0",
        cldr_version="48",
        libpostal_model_sha256="a" * 64,
        phonenumbers_metadata_version="8.13.0",
        dictionaries={"gleif-elf@2023-09": "b" * 64},
        profile_version="v1",
    )


@pytest.mark.unit
def test_env_id_is_stable_across_repeated_computation() -> None:
    inputs = _baseline()
    assert compute_env_id(inputs) == compute_env_id(inputs)


@pytest.mark.unit
def test_env_id_is_stable_regardless_of_dict_insertion_order() -> None:
    a = _baseline()
    b = EnvFingerprintInputs(
        packages={"ftfy": "6.3.1", "phonenumbers": "8.13.0"},  # reordered
        icu_version=a.icu_version,
        unicode_version=a.unicode_version,
        cldr_version=a.cldr_version,
        libpostal_model_sha256=a.libpostal_model_sha256,
        phonenumbers_metadata_version=a.phonenumbers_metadata_version,
        dictionaries=a.dictionaries,
        profile_version=a.profile_version,
    )
    assert compute_env_id(a) == compute_env_id(b)


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda i: setattr(i, "icu_version", "79.0"),
        lambda i: setattr(i, "unicode_version", "18.0"),
        lambda i: setattr(i, "cldr_version", "49"),
        lambda i: setattr(i, "libpostal_model_sha256", "c" * 64),
        lambda i: setattr(i, "phonenumbers_metadata_version", "8.14.0"),
        lambda i: setattr(i, "profile_version", "v2"),
        lambda i: i.packages.__setitem__("ftfy", "6.4.0"),
        lambda i: i.dictionaries.__setitem__("gleif-elf@2023-09", "d" * 64),
    ],
)
def test_env_id_changes_when_any_single_input_changes(mutate) -> None:  # type: ignore[no-untyped-def]
    baseline_id = compute_env_id(_baseline())
    mutated = _baseline()
    mutate(mutated)
    assert compute_env_id(mutated) != baseline_id


@pytest.mark.unit
class TestSourceHashesCloseTheCacheHole:
    """Every other fingerprint input describes the ENVIRONMENT, so a change
    to our own normalizer code used to change normalization output while
    leaving env_id — and therefore the cache key — byte-identical."""

    def test_source_hash_change_changes_env_id(self) -> None:
        a = _baseline()
        a.source_hashes = {"normalizers": "a" * 64}
        b = _baseline()
        b.source_hashes = {"normalizers": "b" * 64}
        assert compute_env_id(a) != compute_env_id(b)

    def test_real_packages_hash_to_stable_nonempty_digests(self) -> None:
        from env_fingerprint import FINGERPRINTED_SOURCE_PACKAGES, collect_source_hashes

        hashes = collect_source_hashes()
        assert set(hashes) == set(FINGERPRINTED_SOURCE_PACKAGES)
        for name, digest in hashes.items():
            assert len(digest) == 64, f"{name} did not hash: {digest}"
        # Same bytes, same digest — env_id must not drift between two
        # calls in one process, nor between two identical checkouts.
        assert collect_source_hashes() == hashes

    def test_editing_a_normalizer_would_change_the_digest(self, tmp_path: Path) -> None:
        """The walk hashes file PATH plus bytes, so neither an edit nor a
        rename can slip through. Exercised on a throwaway tree rather than
        by mutating the real package."""
        import blake3

        def digest_tree(root: Path) -> str:
            out = blake3.blake3()
            for path in sorted(root.rglob("*.py")):
                out.update(path.relative_to(root).as_posix().encode("utf-8"))
                out.update(path.read_bytes())
            return out.hexdigest()

        (tmp_path / "a.py").write_text("x = 1\n")
        before = digest_tree(tmp_path)
        (tmp_path / "a.py").write_text("x = 2\n")
        assert digest_tree(tmp_path) != before
        (tmp_path / "a.py").rename(tmp_path / "b.py")
        assert digest_tree(tmp_path) != before


@pytest.mark.unit
def test_psl_package_is_fingerprinted_and_its_version_moves_env_id() -> None:
    """D9: the Public Suffix List snapshot ships inside `publicsuffixlist`, whose
    version carries the snapshot date, so a PSL update must move env_id."""
    from env_fingerprint import FINGERPRINTED_PACKAGES, collect_package_versions

    assert "publicsuffixlist" in FINGERPRINTED_PACKAGES
    versions = collect_package_versions()
    assert versions["publicsuffixlist"] not in ("", "MISSING")  # actually resolved
    a, b = _baseline(), _baseline()
    a.packages["publicsuffixlist"] = versions["publicsuffixlist"]
    b.packages["publicsuffixlist"] = versions["publicsuffixlist"] + ".1"
    assert compute_env_id(a) != compute_env_id(b)


@pytest.mark.unit
def test_phonetics_package_is_fingerprinted() -> None:
    """D11: Double Metaphone codes come from `phonetics`; its version must move env_id."""
    from env_fingerprint import FINGERPRINTED_PACKAGES, collect_package_versions

    assert "phonetics" in FINGERPRINTED_PACKAGES
    assert collect_package_versions()["phonetics"] not in ("", "MISSING")


@pytest.mark.unit
def test_vendored_rule_data_moves_the_source_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D11: the Beider-Morse rule files are `*.txt` data inside `normalizers`; editing one
    must change the digest exactly like editing code does."""
    from normexec import env_fingerprint

    (tmp_path / "fakepkg").mkdir()
    (tmp_path / "fakepkg" / "__init__.py").write_text("")
    rules = tmp_path / "fakepkg" / "rules.txt"
    rules.write_text('"a" "" "" "a"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(env_fingerprint, "FINGERPRINTED_SOURCE_PACKAGES", ["fakepkg"])
    before = env_fingerprint.collect_source_hashes()["fakepkg"]
    rules.write_text('"a" "" "" "b"\n')
    assert env_fingerprint.collect_source_hashes()["fakepkg"] != before
    # and the real normalizers package really hashes its vendored data
    assert any(
        p.suffix == ".txt" for p in Path(env_fingerprint.__file__).parents[3].rglob("_bmpm_data/*")
    )


@pytest.mark.unit
def test_every_fingerprinted_package_is_a_declared_dependency() -> None:
    """K4/M4: every name in FINGERPRINTED_PACKAGES must be declared in the root
    or a workspace-member pyproject.toml. An undeclared name resolves to
    "MISSING" in collect_package_versions(), which silently shifts env_id
    (ADR-014) on any machine that did not install it — the failure a 2026-10-21
    dependency cleanup hit with `cleanco` (docs/LESSONS.md)."""
    import re
    import tomllib

    from normexec.env_fingerprint import FINGERPRINTED_PACKAGES

    repo = Path(__file__).resolve().parents[2]
    manifests = [repo / "pyproject.toml", *sorted(repo.glob("packages/*/pyproject.toml"))]
    declared: set[str] = set()
    for manifest in manifests:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        for spec in data.get("project", {}).get("dependencies", []):
            name = re.split(r"[<>=!~;\[ ]", spec.strip(), maxsplit=1)[0].lower()
            declared.add(name)
    missing = sorted(
        n
        for n in FINGERPRINTED_PACKAGES
        if n.lower() not in declared and n.lower().replace("-", "_") not in declared
    )
    assert not missing, (
        f"FINGERPRINTED_PACKAGES entries not declared as dependencies: {missing}. "
        "Fix: declare them where used (root or the importing package), or remove "
        "them from FINGERPRINTED_PACKAGES with an ADR — each undeclared name "
        "records 'MISSING' and changes env_id."
    )
