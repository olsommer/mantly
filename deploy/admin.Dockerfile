FROM node:22-alpine AS build

ARG VITE_API_URL
ARG VITE_PB_URL
ARG VITE_ADDIN_URL
ARG VITE_IS_SAAS=true
ARG VITE_REQUIRE_AUTH=true
ARG VITE_ENABLE_ADMIN_PREVIEW=true
ARG VITE_ENABLE_DEMO_MODE=false

ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_PB_URL=${VITE_PB_URL}
ENV VITE_ADDIN_URL=${VITE_ADDIN_URL}
ENV VITE_IS_SAAS=${VITE_IS_SAAS}
ENV VITE_REQUIRE_AUTH=${VITE_REQUIRE_AUTH}
ENV VITE_ENABLE_ADMIN_PREVIEW=${VITE_ENABLE_ADMIN_PREVIEW}
ENV VITE_ENABLE_DEMO_MODE=${VITE_ENABLE_DEMO_MODE}

WORKDIR /app/admin
COPY admin/package.json admin/package-lock.json ./
RUN npm ci
COPY brand.json /app/brand.json
COPY demo /app/demo
COPY admin/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.4-alpine@sha256:44e36330f74d4f3a1d4e222acca9e23b401fb87811a7597024502bb759c4dd49
COPY deploy/spa-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/admin/dist /usr/share/nginx/html
EXPOSE 8080
USER 101:101
