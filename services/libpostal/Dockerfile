# libpostal sidecar: C library built from source (pinned commit) + a thin
# Python/FastAPI batch wrapper. Isolates the ~1.8-2.2GB model data and the
# Windows-unfriendly MSys2/MinGW build requirement away from developer machines.
#
# Model data is pre-fetched on the HOST (see _data_cache/download_data.sh)
# rather than downloaded inside `docker build`. libpostal's own in-container
# downloader (`libpostal_data`, invoked by `make all-local`) opens 12
# parallel connections for the parser model alone; on a bandwidth-constrained
# connection those connections compete with each other and individually
# time out before completing (reproduced twice during M0 — see
# docs/adr/ADR-005-address-normalization.md). A single-connection, resumable
# host-side download of the same three release assets is far more reliable,
# and only needs to happen once since the files are then cached on disk.
# `--disable-data-download` turns off libpostal's own network step entirely;
# we extract the pre-fetched tarballs ourselves at the exact path it would
# have used.
#
# The extracted model data's SHA-256 is recorded to
# /data/libpostal/MODEL_SHA256 — this value is read by env_fingerprint.py and
# folded into every run's env_id (see docs/adr/ADR-014-normalization-versioning.md).

FROM debian:bookworm-slim AS builder

ARG LIBPOSTAL_COMMIT=v1.1.4
ARG LIBPOSTAL_DATA_DIR=/data/libpostal

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential autoconf automake libtool pkg-config \
        curl ca-certificates git python3 python3-pip python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch ${LIBPOSTAL_COMMIT} https://github.com/openvenues/libpostal.git /src/libpostal

# Pre-fetched by _data_cache/download_data.sh — run that script first.
# All three files pin to the v1.0.0 data release regardless of the
# LIBPOSTAL_COMMIT code tag above (libpostal's data and code are versioned
# independently; confirmed against upstream versions/{base_data,parser,
# language_classifier} at the LIBPOSTAL_COMMIT tag).
COPY _data_cache/libpostal_data.tar.gz _data_cache/parser.tar.gz _data_cache/language_classifier.tar.gz /tmp/

WORKDIR /src/libpostal
# NOTE: `./configure --datadir=X` compiles a default of `X/libpostal` into
# the library (see src/Makefile.am's `-DLIBPOSTAL_DATA_DIR='"$(datadir)/libpostal"'`),
# but pypostal's Python wrapper reads the LIBPOSTAL_DATA_DIR *environment
# variable* at runtime and calls libpostal_setup_datadir() with that value
# directly, which takes precedence over the compiled-in default — confirmed
# empirically during M0 (the compiled default and the env-var-driven runtime
# path disagreed, causing "Error loading transliteration module" at import
# time until data was placed at the env-var path instead). Since the final
# image sets ENV LIBPOSTAL_DATA_DIR=${LIBPOSTAL_DATA_DIR} (no "/libpostal"
# suffix) for the server process, data is extracted directly into
# ${LIBPOSTAL_DATA_DIR} here to match what actually gets read at runtime.
RUN mkdir -p ${LIBPOSTAL_DATA_DIR} \
    && tar -xzf /tmp/libpostal_data.tar.gz --no-same-owner -C ${LIBPOSTAL_DATA_DIR} \
    && tar -xzf /tmp/parser.tar.gz --no-same-owner -C ${LIBPOSTAL_DATA_DIR} \
    && tar -xzf /tmp/language_classifier.tar.gz --no-same-owner -C ${LIBPOSTAL_DATA_DIR} \
    && rm -f /tmp/*.tar.gz \
    && ./bootstrap.sh \
    && ./configure --datadir=${LIBPOSTAL_DATA_DIR} --disable-data-download \
    && make -j"$(nproc)" \
    && make install \
    && ldconfig

RUN sha256sum -b $(find ${LIBPOSTAL_DATA_DIR} -type f | sort) \
      | sha256sum | awk '{print $1}' > ${LIBPOSTAL_DATA_DIR}/MODEL_SHA256

# Build the pypostal wheel here, where gcc/libpostal headers are present —
# the final runtime stage stays slim (no compiler) and just installs the
# prebuilt wheel. pypostal's C extension links against libpostal at build
# time, so this must happen after `make install` above.
COPY requirements.txt /app/requirements.txt
RUN pip wheel --no-cache-dir -r /app/requirements.txt -w /wheels

FROM debian:bookworm-slim

ARG LIBPOSTAL_DATA_DIR=/data/libpostal
ENV LIBPOSTAL_DATA_DIR=${LIBPOSTAL_DATA_DIR}

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /usr/local/include/libpostal/ /usr/local/include/libpostal/
COPY --from=builder ${LIBPOSTAL_DATA_DIR} ${LIBPOSTAL_DATA_DIR}
RUN ldconfig

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --break-system-packages --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

COPY server.py /app/server.py
WORKDIR /app

EXPOSE 8081
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=60s \
    CMD curl -f http://localhost:8081/health || exit 1

CMD ["python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8081"]
