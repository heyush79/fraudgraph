# ---- build ----
FROM node:22-alpine AS build
WORKDIR /app

# Install deps from the lockfile first so this layer caches across source edits.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Same-origin by default: nginx below proxies the API and the agent, so no base
# URL is baked in.
ARG VITE_API_BASE=""
# "true" for any public deployment: hides the case-status control
# (docs/showcase-contract.md section 1). This image is always live mode; the
# replay build is `npm run build:replay`, published as static files.
ARG VITE_READ_ONLY=""
ENV VITE_API_BASE=$VITE_API_BASE VITE_READ_ONLY=$VITE_READ_ONLY
RUN npm run build

# ---- serve ----
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY proxy-common.conf /etc/nginx/fraudgraph-proxy.conf
# PUBLIC_MODE=true at run time (deploy/) makes the proxy read-only apart from questions to
# the analyst; the script picks the rule set before nginx starts.
COPY public-mode.conf /etc/nginx/fraudgraph-public-mode.on
COPY --chmod=0755 docker-entrypoint.d/40-public-mode.sh /docker-entrypoint.d/40-public-mode.sh
RUN : > /etc/nginx/fraudgraph-public-mode.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
CMD ["nginx", "-g", "daemon off;"]
