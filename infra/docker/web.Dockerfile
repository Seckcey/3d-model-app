# Builds the React app and serves it from nginx, which also proxies the API,
# serves protected downloads (X-Accel-Redirect) and listens on 8080.
FROM node:24-alpine AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM nginx:stable-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY infra/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY infra/nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /web/dist /usr/share/nginx/html
ENV MAX_BODY_MB=30
EXPOSE 8080
