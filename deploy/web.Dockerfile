FROM node:26.13.0-trixie-slim AS dependencies
WORKDIR /app
RUN chown node:node /app
USER node
COPY --chown=node:node web/package.json web/package-lock.json ./
RUN npm ci --no-fund --no-audit

# Runs the Vite server against the source that compose.dev.yaml mounts into /app.
FROM dependencies AS dev
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM dependencies AS build
COPY --chown=node:node web/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine AS production
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
