# syntax=docker/dockerfile:1.7
#
# Two targets from one file:
#   api  – API, CPU worker and `siqe init`. No PyTorch, so it stays small.
#   ai   – GPU worker (and later the trainer). Adds PyTorch with CUDA; also runs on CPU.
#
# Behind a TLS-intercepting proxy, pass its CA as a build secret (never stored in the image):
#   docker build --secret id=extra_ca,src=/path/to/ca.pem ...

ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    MALLOC_ARENA_MAX=2 \
    PATH="/app/.venv/bin:${PATH}"
WORKDIR /app
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir --root-user-action=ignore "uv>=0.8,<1" \
 && groupadd --system --gid 1000 siqe \
 && useradd --system --uid 1000 --gid siqe --home-dir /app --shell /usr/sbin/nologin siqe \
 && mkdir -p /data && chown siqe:siqe /data

# ---------------------------------------------------------------------------- api
FROM base AS api
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-editable
ARG SIQE_VERSION=0.0.0-dev
ENV SIQE_VERSION=${SIQE_VERSION}
USER siqe
VOLUME ["/data"]
EXPOSE 8000
CMD ["siqe", "api"]

# ----------------------------------------------------------------------------- ai
FROM base AS ai
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-install-project --extra ai
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-editable --extra ai
ARG SIQE_VERSION=0.0.0-dev
ENV SIQE_VERSION=${SIQE_VERSION}
USER siqe
VOLUME ["/data"]
CMD ["siqe", "worker", "gpu"]
