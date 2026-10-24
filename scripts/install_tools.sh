#!/usr/bin/env bash
# Install the pinned guard binaries locally with checksum verification (K4,
# user decision 2026-10-24: project-local, never global). Binaries land in
# .tools/ (git-ignored). CI runs this same script (guards.yml) — it also
# makes `./.tools/gitleaks` and `./.tools/actionlint` work locally.
#
# Python guard tools are NOT here: deptry, vulture and zizmor come from the
# dev extra (`uv sync --all-extras`, run via `uv run ...`), pinned in
# pyproject.toml.
#
# To bump a version: update VERSION, URL and SHA256 together, from the
# project's own release checksums file.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .tools

install() {
    local name="$1" url="$2" sha="$3" file
    file=".tools/$(basename "$url")"
    if [ -x ".tools/$name" ]; then
        echo "$name: already present in .tools/ — remove it first to reinstall"
        return 0
    fi
    curl -fsSL -o "$file" "$url"
    echo "$sha  $file" | sha256sum -c -
    tar xzf "$file" -C .tools "$name"
    rm "$file"
    ".tools/$name" --version | head -1
}

# gitleaks v8.30.1 (MIT) — B6 secret scan
# checksum from https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_checksums.txt
install gitleaks \
    "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz" \
    "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"

# actionlint v1.7.12 (MIT) — CI workflow lint
# checksum from https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_checksums.txt
install actionlint \
    "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz" \
    "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"
