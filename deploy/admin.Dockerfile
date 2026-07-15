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

FROM nginx:1.27-alpine
COPY deploy/spa-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/admin/dist /usr/share/nginx/html
EXPOSE 80
