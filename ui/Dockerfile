# M22 — one-command startup (docs/plan/M13-M22-program-plan.md). Multi-stage:
# a real `vite build` in a node builder stage, served by nginx in the
# runtime stage. Pinned to node's own `-bookworm` suffix for the same
# reason packages/normapi/Dockerfile pins python: an unpinned floating tag
# drifting to a different Debian release out from under a built image is a
# real failure mode already hit once in this project (M7's Docker follow-up).
FROM node:22-bookworm AS builder

WORKDIR /app
COPY ui/package.json ui/package-lock.json ./
RUN npm ci

COPY ui/ ./

# Vite bakes VITE_* vars into the built bundle at build time, not runtime.
# Empty string (not unset) makes ui/src/api/client.ts's
# `API_BASE ?? "http://localhost:8080"` fallback correctly NOT apply
# (nullish coalescing only falls back on null/undefined) — so every real
# API call becomes a same-origin relative path (`/normalization/...`),
# which nginx.conf below reverse-proxies to the real `api` service. This
# is the actual fix for the plan's own callout: "behind nginx the UI's
# API base must become relative."
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM nginx:1.27-alpine

COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=10s \
    CMD wget -qO- http://127.0.0.1:80/ || exit 1
