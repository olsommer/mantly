FROM node:22-alpine AS build

WORKDIR /app/landing
COPY landing/package.json landing/package-lock.json ./
RUN npm ci
COPY brand.json /app/brand.json
COPY demo /app/demo
COPY landing/ ./
ARG VITE_PUBLIC_POSTHOG_TOKEN
ARG VITE_PUBLIC_POSTHOG_HOST
ENV VITE_PUBLIC_POSTHOG_TOKEN=${VITE_PUBLIC_POSTHOG_TOKEN}
ENV VITE_PUBLIC_POSTHOG_HOST=${VITE_PUBLIC_POSTHOG_HOST}
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.4-alpine@sha256:44e36330f74d4f3a1d4e222acca9e23b401fb87811a7597024502bb759c4dd49
COPY deploy/landing-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/landing/dist /usr/share/nginx/html
EXPOSE 8080
USER 101:101
