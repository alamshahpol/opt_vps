# Selected owner fork baseline 895404542017f34a900f9f572a5497c275a96440.
FROM golang:1.26-bookworm@sha256:d9c68c2c51161e12fd77e4c6320687c9cd86e1af1e3ad6e6cd63ff970641453c AS go-deps
ENV CGO_ENABLED=1 GOTOOLCHAIN=local
WORKDIR /src
COPY whatsapp-bridge/go.mod whatsapp-bridge/go.sum ./
RUN go version && gcc --version && go mod download && go mod verify
FROM go-deps AS go-test
COPY whatsapp-bridge/ ./
RUN test -z "$(gofmt -l *.go)" && go vet ./... && go test ./... && go build -trimpath -o /out/whatsapp-bridge .

FROM ghcr.io/astral-sh/uv:0.10.0@sha256:78a7ff97cd27b7124a5f3c2aefe146170793c56a1e03321dd31a289f6d82a04f AS uv
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS python-base
COPY --from=uv /uv /usr/local/bin/uv
# Immutable Debian snapshot keeps runtime FFmpeg dependencies repeatable.
RUN rm /etc/apt/sources.list.d/debian.sources && printf '%s\n' \
 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261009T000000Z bookworm main' \
 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20261009T000000Z bookworm-security main' \
 > /etc/apt/sources.list && apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/whatsapp-mcp-server
COPY whatsapp-mcp-server/ ./
FROM python-base AS python-tooling
RUN uv sync --locked --extra dev --python /usr/local/bin/python
FROM python-tooling AS python-test
RUN uv run --python /usr/local/bin/python --no-sync ruff check . && uv run --python /usr/local/bin/python --no-sync ruff format --check . && uv run --python /usr/local/bin/python --no-sync pytest -q
FROM python-base AS python-runtime
RUN uv sync --locked --no-dev --python /usr/local/bin/python && uv --version && python --version && ffmpeg -version > /app/ffmpeg-version.txt && dpkg-query -W > /app/os-packages.txt
FROM python-runtime AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends wget && rm -rf /var/lib/apt/lists/*
COPY --from=go-test /out/whatsapp-bridge /usr/local/bin/whatsapp-bridge
COPY --from=python-test /app/whatsapp-mcp-server/pyproject.toml /app/qualification-python-manifest.toml
COPY mcp-client.py /app/mcp-client.py
COPY service-entrypoint.sh /usr/local/bin/service-entrypoint
ENV WHATSAPP_DB_PATH=/runtime/store/messages.db WHATSMEOW_DB_PATH=/runtime/store/whatsapp.db WHATSAPP_API_URL=http://127.0.0.1:8080/api WHATSAPP_MEDIA_ROOTS=/runtime/outbox WHATSAPP_MCP_TRANSPORT=stdio WEBHOOK_ENABLED=false WHATSAPP_AUTO_DOWNLOAD_MEDIA=false WHATSAPP_LOG_CONTENT=false
USER 10002:10002
WORKDIR /runtime
ENTRYPOINT ["/usr/local/bin/service-entrypoint"]
CMD ["service", "--wait-unpaired"]
