"""Real integration test: AddressNormalizer against the LIVE libpostal
sidecar container (not a fake/mock) — Gate G4's "libpostal sidecar
liveness proven including its failure path" requirement.

Requires `docker compose up -d libpostal` first.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from normalizers.address import AddressNormalizer, LibpostalClient, LibpostalUnavailableError
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, QualityFlag

_LIBPOSTAL_URL = "http://localhost:8081"


@pytest.fixture(scope="module")
def libpostal_client() -> Iterator[LibpostalClient]:
    client = LibpostalClient(_LIBPOSTAL_URL)
    try:
        client.health()
    except Exception as exc:
        pytest.skip(f"libpostal sidecar not reachable at {_LIBPOSTAL_URL}: {exc}")
    yield client
    client.close()


@pytest.fixture(scope="module")
def normalizer(libpostal_client: LibpostalClient) -> AddressNormalizer:
    return AddressNormalizer(libpostal_client)


@pytest.fixture(scope="module")
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="address", semantic_type=FieldSemanticType.ADDRESS)


@pytest.mark.integration
def test_sidecar_health_reports_model_checksum(libpostal_client: LibpostalClient) -> None:
    health = libpostal_client.health()
    assert health["status"] == "ok"
    assert health["model_sha256"]


@pytest.mark.integration
def test_version_reports_the_real_model_sha256(libpostal_client: LibpostalClient) -> None:
    """§73/ADR-014's env_id needs this — real proof `GET /version`
    (services/libpostal/server.py) returns the same model checksum
    `/health` does, against the live sidecar, not a mock."""
    version = libpostal_client.version()
    health = libpostal_client.health()
    assert version == health["model_sha256"]
    assert version is not None


@pytest.mark.integration
def test_uk_address_from_source_txt_109(
    normalizer: AddressNormalizer, ctx: NormalizationContext
) -> None:
    """Source.txt §109's own worked example."""
    result = normalizer.normalize("10-12 Baker St., London, W1U 3BW, UK", ctx)
    assert result.structured["house_number"] == "10-12"
    assert result.structured["postcode_valid"] is True


@pytest.mark.integration
def test_us_address_from_source_txt_109(
    normalizer: AddressNormalizer, ctx: NormalizationContext
) -> None:
    result = normalizer.normalize("1600 Pennsylvania Avenue NW, Washington, DC 20500, USA", ctx)
    assert result.structured["house_number"] == "1600"
    assert result.structured["postcode"] == "20500"
    assert result.structured["postcode_valid"] is True


@pytest.mark.integration
def test_real_parse_produces_full_component_trace(
    normalizer: AddressNormalizer, ctx: NormalizationContext
) -> None:
    result = normalizer.normalize("123 Main St, Toronto, ON M5V 3A8, Canada", ctx)
    operations = [step.operation for step in result.trace]
    assert "address.libpostal_parse" in operations


@pytest.mark.integration
def test_failure_path_against_unreachable_sidecar(ctx: NormalizationContext) -> None:
    """Gate G4's explicit "including its failure path" requirement —
    proven against a real (deliberately wrong) endpoint, not a mock."""
    dead_client = LibpostalClient("http://localhost:1", timeout=1.0)
    normalizer_with_dead_sidecar = AddressNormalizer(dead_client)
    result = normalizer_with_dead_sidecar.normalize("123 Main St", ctx)
    assert QualityFlag.PARSER_FALLBACK in result.flags
    dead_client.close()


@pytest.mark.integration
def test_libpostal_client_raises_typed_error_on_unreachable_host() -> None:
    dead_client = LibpostalClient("http://localhost:1", timeout=1.0)
    with pytest.raises(LibpostalUnavailableError):
        dead_client.parse("123 Main St")
    dead_client.close()


@pytest.mark.integration
def test_version_gracefully_returns_none_against_unreachable_host() -> None:
    """Unlike `parse()`, `version()` must never raise — env_id
    computation happens at API startup and must not crash the whole
    process just because the sidecar isn't reachable yet."""
    dead_client = LibpostalClient("http://localhost:1", timeout=1.0)
    assert dead_client.version() is None
    dead_client.close()
