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

FROM nginx:1.27-alpine
COPY deploy/landing-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/landing/dist /usr/share/nginx/html
EXPOSE 80
