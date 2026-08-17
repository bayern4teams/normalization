# libpostal model data cache

Run `download_data.sh` once to fetch libpostal's three release data assets
(`libpostal_data.tar.gz`, `language_classifier.tar.gz`, `parser.tar.gz` —
~813MB total, all pinned to the `v1.0.0` data release) via a single-connection,
resumable download.

**Why this exists**: libpostal's own build (`make all-local`) downloads the
same files using 12 parallel connections for the parser file alone. On a
bandwidth-constrained connection those connections compete with each other
and individually time out before completing — reproduced twice during M0.
See `docs/adr/ADR-005-address-normalization.md` for the full root-cause
analysis. `services/libpostal/Dockerfile` is configured with
`--disable-data-download` and expects the three `*.tar.gz` files in this
directory to already exist before `docker build` runs.

```bash
bash services/libpostal/_data_cache/download_data.sh
```

Safe to re-run — `curl -C -` resumes any partial download rather than
restarting. The `*.tar.gz` files are gitignored; CI caches them by content
hash of `download_data.sh` (see `.github/workflows/ci-full.yml` and
`gate.yml`) so they are fetched once per script version, not every run.
