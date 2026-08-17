"""License allow-list gate.

Reads scripts/license_policy.toml, inspects the resolved environment's
installed package metadata (via importlib.metadata), classifies each
package's declared license, and fails (exit 1) if:

  - any package's license is in the `denied` list, or
  - any package's license is LGPL and the package is NOT in
    `allowed_unmodified_dynamic_only.packages`, or
  - any package name is in `explicitly_rejected_packages`.

This is intentionally conservative: an unrecognized/unclassifiable license
is treated as a WARNING (not a hard failure) but is printed prominently so a
human reviews it during the milestone verification pack step.

Run: uv run python scripts/check_licenses.py
"""

from __future__ import annotations

import sys
import tomllib
from importlib.metadata import distributions
from pathlib import Path

POLICY_PATH = Path(__file__).parent / "license_policy.toml"


def normalize_license(raw: str) -> str:
    raw = raw.strip()
    aliases = {
        "MIT License": "MIT",
        "Apache Software License": "Apache-2.0",
        "Apache License 2.0": "Apache-2.0",
        "BSD License": "BSD-3-Clause",
        "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.1-or-later",
        "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
        "GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
        "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
        "The Unlicense (Unlicense)": "Unlicense",
        "Python Software Foundation License": "PSF-2.0",
    }
    return aliases.get(raw, raw)


def load_policy() -> dict:
    with POLICY_PATH.open("rb") as fh:
        return tomllib.load(fh)


def collect_installed_licenses() -> dict[str, str]:
    result: dict[str, str] = {}
    for dist in distributions():
        name = dist.metadata.get("Name")
        if not name:
            continue
        license_expr = dist.metadata.get("License-Expression")
        classifiers = dist.metadata.get_all("Classifier") or []
        license_classifiers = [c for c in classifiers if c.startswith("License ::")]
        if license_expr:
            license_value = license_expr
        elif license_classifiers:
            license_value = license_classifiers[-1].split("::")[-1].strip()
        else:
            license_value = dist.metadata.get("License", "UNKNOWN")
        result[name] = normalize_license(license_value or "UNKNOWN")
    return result


def evaluate(policy: dict, installed: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    allowed = set(policy["allowed"]["licenses"])
    lgpl_allowed_licenses = set(policy["allowed_unmodified_dynamic_only"]["licenses"])
    lgpl_allowed_packages = {
        p.lower() for p in policy["allowed_unmodified_dynamic_only"]["packages"]
    }
    denied = set(policy["denied"]["licenses"])
    rejected_packages = {p.lower() for p in policy["denied"]["explicitly_rejected_packages"]}

    for pkg_name, license_value in sorted(installed.items()):
        pkg_lower = pkg_name.lower()

        if pkg_lower in rejected_packages:
            errors.append(
                f"{pkg_name}: explicitly rejected package present in environment "
                f"(see docs/normalization-tool-evaluation.md). Remove it."
            )
            continue

        if license_value in denied:
            errors.append(f"{pkg_name}: license '{license_value}' is on the denied list.")
            continue

        if license_value in allowed:
            continue

        if license_value in lgpl_allowed_licenses:
            if pkg_lower in lgpl_allowed_packages:
                continue
            errors.append(
                f"{pkg_name}: license '{license_value}' is LGPL and is only permitted for "
                f"{sorted(lgpl_allowed_packages)}. Add to policy explicitly via ADR if this "
                f"is a deliberate new LGPL dependency, used unmodified and dynamically imported."
            )
            continue

        warnings.append(
            f"{pkg_name}: unrecognized/unclassified license '{license_value}' — needs human review."
        )

    return errors, warnings


def main() -> int:
    policy = load_policy()
    installed = collect_installed_licenses()
    errors, warnings = evaluate(policy, installed)

    if warnings:
        print("License warnings (review required, non-blocking):")
        for w in warnings:
            print(f"  ! {w}")

    if errors:
        print("\nLicense policy violations (BLOCKING):", file=sys.stderr)
        for e in errors:
            print(f"  x {e}", file=sys.stderr)
        return 1

    print(
        f"\nLicense check passed: {len(installed)} packages inspected, "
        f"0 violations, {len(warnings)} warnings."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
