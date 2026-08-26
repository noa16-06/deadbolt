# syntax=docker/dockerfile:1
#
# Frontend image: build the Vite bundle, serve it with nginx. The same nginx
# also proxies /api to the backend — that is what the Vite dev server does in
# development, and it keeps the origin in the browser identical, so the session
# cookie needs no CORS special case.
#
# Build context is frontend/.

FROM node:22-alpine AS build

WORKDIR /build

# The lockfile decides the versions — npm ci, not npm install.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Unprivileged nginx: listens on 8080 and runs as uid 101, so nothing here
# needs root.
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /build/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/"]
