FROM caddy:2-alpine

RUN apk add --no-cache --virtual .setcap-deps libcap \
    && addgroup -S -g 10001 mantly \
    && adduser -S -D -H -u 10001 -G mantly mantly \
    && setcap cap_net_bind_service=+ep /usr/bin/caddy \
    && chown -R mantly:mantly /data /config \
    && apk del .setcap-deps

COPY --chmod=0444 caddy/Caddyfile /etc/caddy/Caddyfile

USER mantly:mantly
