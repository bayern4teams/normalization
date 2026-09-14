#!/bin/bash
set -e
# Run from the repo root per the docs (`bash services/libpostal/_data_cache/
# download_data.sh`) or with a relative/bare `./download_data.sh` from
# inside this directory — either way, downloads must land here, not in
# whatever directory the caller happened to be in. Without this `cd`,
# following the docs' own literal invocation put the files in the repo
# root instead, where the Dockerfile's `COPY _data_cache/*.tar.gz` can't
# find them (found by actually running the documented command).
cd "$(dirname "$0")"
BASE_URL="https://github.com/openvenues/libpostal/releases/download/v1.0.0"
for f in libpostal_data.tar.gz language_classifier.tar.gz parser.tar.gz; do
  echo "=== Downloading $f ==="
  curl -SL -C - --retry 10 --retry-delay 5 --retry-all-errors -o "$f" "$BASE_URL/$f"
  echo "=== Done: $f ($(stat -c%s "$f" 2>/dev/null || stat -f%z "$f") bytes) ==="
done
echo "ALL_DOWNLOADS_COMPLETE"
