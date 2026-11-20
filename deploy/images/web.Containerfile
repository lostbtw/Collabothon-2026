FROM registry.access.redhat.com/ubi9/nodejs-22 AS build

USER 0
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --no-audit --no-fund

COPY contracts ./contracts
COPY frontend ./frontend

ARG VITE_API_MODE=live
RUN cd frontend && VITE_API_MODE="$VITE_API_MODE" npm run build

FROM registry.access.redhat.com/ubi9/nginx-126

COPY deploy/images/web-nginx.conf /etc/nginx/nginx.conf
COPY frontend/nginx.conf /opt/app-root/etc/nginx.d/ordo.conf
COPY --from=build /build/frontend/dist /usr/share/nginx/html

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
