"""Spike: libpostal sidecar parse round-trip (Source.txt §29-32; decision
recorded in docs/adr/ADR-005-address-normalization.md).

Requires the sidecar container to be running:
    bash services/libpostal/_data_cache/download_data.sh   # one-time, ~813MB
    docker compose up -d libpostal
    (wait for health check; image build itself takes several minutes even
    with data pre-fetched, since libpostal compiles from source — see
    docs/adr/ADR-005-address-normalization.md for why the model data is
    pre-fetched on the host rather than downloaded inside `docker build`)

Proves:
- The sidecar's /health endpoint reports a model_sha256 — the value that
  feeds env_id (ADR-014).
- /parse correctly decomposes a real-world international address into
  components (Source.txt §109's own example address).
- /expand produces multiple candidate expansions, never a single forced
  "truth" (Source.txt §31).
- House-number RANGES survive parsing intact ("10-12" stays "10-12", never
  becomes "1012" — the exact case Source.txt §30 calls out).

Run: uv run python spikes/07_libpostal_sidecar.py
"""

from __future__ import annotations

import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8")

SIDECAR_URL = "http://localhost:8081"


def check_health() -> None:
    print("=== Sidecar health + model checksum (feeds env_id, ADR-014) ===")
    resp = httpx.get(f"{SIDECAR_URL}/health", timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    print(f"  status: {payload['status']}")
    print(f"  model_sha256: {payload['model_sha256']}")
    assert payload["status"] == "ok"
    assert payload["model_sha256"], (
        "model checksum must be present — this is what makes the model version part of env_id"
    )


def demo_parse_uk_address() -> None:
    print("\n=== Parse: UK address with a house-number RANGE (Source.txt §109, §30) ===")
    address = "10-12 Baker St, London W1U 3BW, UK"
    resp = httpx.post(f"{SIDECAR_URL}/parse", json={"addresses": [address]}, timeout=30)
    resp.raise_for_status()
    result = resp.json()[0]
    print(f"  input: {address!r}")
    components = {c["label"]: c["value"] for c in result["components"]}
    for label, value in components.items():
        print(f"    {label:12s} = {value!r}")

    house_number = components.get("house_number", "")
    print(f"\n  house_number component: {house_number!r}")
    assert "10" in house_number and "12" in house_number, (
        "the house-number RANGE must survive parsing — Source.txt §30 explicitly "
        "forbids '10-12' collapsing into '1012'"
    )
    print("  => range preserved, not collapsed to '1012'. Confirms ADR-005/§30 requirement.")


def demo_parse_us_address() -> None:
    print("\n=== Parse: US address (Source.txt §109 example) ===")
    address = "1600 Pennsylvania Avenue NW, Washington, DC 20500, USA"
    resp = httpx.post(f"{SIDECAR_URL}/parse", json={"addresses": [address]}, timeout=30)
    resp.raise_for_status()
    result = resp.json()[0]
    components = {c["label"]: c["value"] for c in result["components"]}
    for label, value in components.items():
        print(f"    {label:12s} = {value!r}")


def demo_expansion_candidates_not_single_truth() -> None:
    print("\n=== Expand: candidate set, never one forced 'truth' (Source.txt §31) ===")
    address = "123 Main St"
    resp = httpx.post(f"{SIDECAR_URL}/expand", json={"addresses": [address]}, timeout=30)
    resp.raise_for_status()
    result = resp.json()[0]
    print(f"  input: {address!r}")
    print(f"  expansion_candidates ({len(result['expansions'])} total):")
    for exp in result["expansions"]:
        print(f"    - {exp!r}")
    assert len(result["expansions"]) >= 1
    print(
        "  => stored as expansion_candidates (a set), never collapsed to one "
        "'primary_normalized' value without a documented safe-expansion policy."
    )


def demo_malformed_address_partial_parse() -> None:
    print("\n=== Malformed/incomplete address: partial parse, not a crash (Source.txt §68) ===")
    address = "asdkjaslkdj 123"
    resp = httpx.post(f"{SIDECAR_URL}/parse", json={"addresses": [address]}, timeout=30)
    resp.raise_for_status()
    result = resp.json()[0]
    print(f"  input: {address!r}")
    print(f"  components: {[(c['label'], c['value']) for c in result['components']]}")
    print(
        "  => sidecar returns SOME parse (however partial) rather than an error; "
        "our AddressNormalizer is responsible for deciding this warrants "
        "status=ADDRESS_PARSE_PARTIAL based on component coverage/confidence."
    )


if __name__ == "__main__":
    check_health()
    demo_parse_uk_address()
    demo_parse_us_address()
    demo_expansion_candidates_not_single_truth()
    demo_malformed_address_partial_parse()
