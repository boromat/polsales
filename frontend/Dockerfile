# Build frontendu i obraz Caddy, który go serwuje (deploy/docker-compose.yml, usługa caddy).
FROM node:24-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /src/dist /srv/frontend
