# syntax=docker/dockerfile:1.7
#
# PaperMind frontend image: build the SPA, then serve the static output
# from nginx. The Node toolchain never reaches the runtime image.

# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy manifests first so `npm ci` is cached until dependencies actually change.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Baked in at build time: Vite inlines VITE_* variables into the bundle.
# Empty means "same origin", which is what the nginx proxy below serves.
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build


# ── Stage 2: serve ────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/*
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# nginx:alpine ships an unprivileged `nginx` user; give it the dirs it writes to.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:8080/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
