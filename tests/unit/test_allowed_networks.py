"""R14: the deployer setting adds networks; it never skips bad input (ADR-022)."""

import pytest
from normapi.address_policy import check_caller, classify, resolve_and_check


def test_cgnat_is_refused_until_the_setting_adds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # 100.64.0.0/10 is shared address space, RFC 6598: not in the built-in set.
    monkeypatch.delenv("NORM_ALLOWED_NETWORKS", raising=False)
    assert not classify("100.64.0.1")
    monkeypatch.setenv("NORM_ALLOWED_NETWORKS", "100.64.0.0/10")
    assert classify("100.64.0.1")
    assert check_caller("100.127.255.254")
    assert not check_caller("100.128.0.1")
    assert resolve_and_check("100.64.0.1") == "100.64.0.1"


def test_setting_does_not_open_anything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORM_ALLOWED_NETWORKS", "100.64.0.0/10")
    assert not classify("8.8.8.8")


@pytest.mark.parametrize("bad", ["not-a-network", "10.0.0.1/8", "100.64.0.0/33"])
def test_bad_setting_is_refused_not_skipped(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("NORM_ALLOWED_NETWORKS", bad)
    with pytest.raises(ValueError, match=r"\S"):
        classify("10.0.0.1")
