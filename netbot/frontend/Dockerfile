FROM node:24-alpine AS build
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.mjs styles.css ./
COPY src ./src
COPY modules ./modules
COPY chat-reservations.mjs ./chat-reservations.mjs
COPY public ./public
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /frontend/dist /opt/netbot/frontend/dist
