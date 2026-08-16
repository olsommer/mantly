FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget unzip ca-certificates && rm -rf /var/lib/apt/lists/*

ENV POCKETBASE_VERSION=0.36.5

RUN groupadd --gid 10001 mantly \
    && useradd --uid 10001 --gid mantly --home-dir /pb --no-create-home --shell /usr/sbin/nologin mantly

RUN mkdir -p /pb/pb_data /pb/pb_migrations /pb/pb_hooks

# Download PocketBase at build time (supports amd64 + arm64 via TARGETARCH)
ARG TARGETARCH
RUN PB_ARCH="${TARGETARCH}"; \
    if [ "$PB_ARCH" = "amd64" ]; then PB_ARCH="amd64"; \
    elif [ "$PB_ARCH" = "arm64" ]; then PB_ARCH="arm64"; \
    else PB_ARCH="amd64"; fi; \
    PB_URL="https://github.com/pocketbase/pocketbase/releases/download/v${POCKETBASE_VERSION}/pocketbase_${POCKETBASE_VERSION}_linux_${PB_ARCH}.zip"; \
    echo "Downloading PocketBase ${POCKETBASE_VERSION} (${PB_ARCH})..."; \
    wget -qO /tmp/pb.zip "$PB_URL" && \
    unzip -o /tmp/pb.zip pocketbase -d /pb/ && \
    chmod +x /pb/pocketbase && \
    rm /tmp/pb.zip

# Copy migrations from repo root (build context is the repo root)
COPY backend/pb_migrations/ /pb/pb_migrations/
COPY pocketbase/pb_hooks/ /pb/pb_hooks/
COPY THIRD_PARTY_NOTICES.md /usr/share/doc/mantly/THIRD_PARTY_NOTICES.md
COPY third_party/pocketbase/LICENSE /usr/share/licenses/pocketbase/LICENSE

COPY pocketbase/start.sh /start.sh
RUN chmod +x /start.sh && chown -R mantly:mantly /pb/pb_data

USER mantly:mantly

VOLUME ["/pb/pb_data"]
EXPOSE 8090

CMD ["/start.sh"]
