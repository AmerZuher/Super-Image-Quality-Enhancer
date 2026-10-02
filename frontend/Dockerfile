# syntax=docker/dockerfile:1.7
#
# Builds the SPA and serves it with Caddy, which also proxies /api to the backend.
# Build context is the repository root (it needs deploy/caddy/Caddyfile).

FROM node:26-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm install --global --no-fund --no-audit pnpm@12.8.1 \
 && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM caddy:2 AS web
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
EXPOSE 8080
