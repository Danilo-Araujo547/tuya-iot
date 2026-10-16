FROM node:22-alpine AS build
WORKDIR /frontend
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM caddy:2-alpine
COPY --from=build /frontend/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
