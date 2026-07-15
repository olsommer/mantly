# Stage 1 — Build Outlook add-in
FROM node:22-alpine AS addin-build

# VITE_PB_URL: path or URL where the browser reaches PocketBase for auth.
#   Production (Caddy proxy): "/pb"   — same-origin, no CORS.
#   Local dev:                "http://localhost:8090"
ARG VITE_PB_URL=/pb
ARG VITE_API_URL=
ARG VITE_ADDIN_BASE_PATH=/addin/
ARG VITE_ENABLE_ADMIN_PREVIEW=true
ARG VITE_ENABLE_DEMO_MODE=false
ENV VITE_PB_URL=${VITE_PB_URL}
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_ADDIN_BASE_PATH=${VITE_ADDIN_BASE_PATH}
ENV VITE_REQUIRE_AUTH=true
ENV VITE_ENABLE_MOCK_MODE=false
ENV VITE_ENABLE_ADMIN_PREVIEW=${VITE_ENABLE_ADMIN_PREVIEW}
ENV VITE_ENABLE_DEMO_MODE=${VITE_ENABLE_DEMO_MODE}

WORKDIR /app/addin
COPY addin/package.json addin/package-lock.json ./
RUN npm ci
COPY brand.json /app/brand.json
COPY demo /app/demo
COPY addin/ ./
RUN npm run build

# Stage 2 — Build admin SPA
FROM node:22-alpine AS admin-build

ARG VITE_PB_URL=/pb
ARG VITE_API_URL=
ARG VITE_IS_SAAS=false
ARG VITE_ENABLE_ADMIN_PREVIEW=true
ARG VITE_ENABLE_DEMO_MODE=false
ENV VITE_PB_URL=${VITE_PB_URL}
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_IS_SAAS=${VITE_IS_SAAS}
ENV VITE_REQUIRE_AUTH=true
ENV VITE_ENABLE_ADMIN_PREVIEW=${VITE_ENABLE_ADMIN_PREVIEW}
ENV VITE_ENABLE_DEMO_MODE=${VITE_ENABLE_DEMO_MODE}

WORKDIR /app/admin
COPY admin/package.json admin/package-lock.json ./
RUN npm ci
COPY brand.json /app/brand.json
COPY demo /app/demo
COPY admin/ ./
RUN npm run build

# Stage 3 — Backend runtime
FROM python:3.12-slim

RUN pip install "uv>=0.7,<1"

# Create non-root user for security
RUN useradd -m -u 1000 appuser

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./
RUN mkdir -p /app/backend/resources
COPY brand.json /app/brand.json
COPY demo /app/demo
COPY addin/manifest.xml /app/backend/resources/manifest.xml

# Copy icon assets for Outlook manifest
COPY backend/assets/ /app/backend/assets/

# Copy addin and admin builds from build stages
COPY --from=addin-build /app/addin/dist /app/addin/dist
COPY --from=admin-build /app/admin/dist /app/admin/dist

# Ensure data directory exists and is writable by appuser
RUN mkdir -p /app/data/attachments && chown -R appuser:appuser /app

RUN chmod +x /app/backend/start.sh

ENV STATIC_FILES_DIR=/app/addin/dist
ENV ADMIN_STATIC_FILES_DIR=/app/admin/dist
ENV MANIFEST_TEMPLATE_PATH=/app/backend/resources/manifest.xml
ENV ASSETS_DIR=/app/backend/assets
ENV ATTACHMENTS_DIR=/app/data/attachments

# Persist data (attachments, SQLite, license cache) across container restarts
VOLUME ["/app/data"]

EXPOSE 8080

# Switch to non-root user
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

CMD ["/app/backend/start.sh"]
