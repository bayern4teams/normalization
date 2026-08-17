#!/bin/bash
set -e
BASE_URL="https://github.com/openvenues/libpostal/releases/download/v1.0.0"
for f in libpostal_data.tar.gz language_classifier.tar.gz parser.tar.gz; do
  echo "=== Downloading $f ==="
  curl -SL -C - --retry 10 --retry-delay 5 --retry-all-errors -o "$f" "$BASE_URL/$f"
  echo "=== Done: $f ($(stat -c%s "$f" 2>/dev/null || stat -f%z "$f") bytes) ==="
done
echo "ALL_DOWNLOADS_COMPLETE"
