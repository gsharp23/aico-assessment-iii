# Multi-stage build: compile the React app with Node, then serve the static
# output with nginx. The final image carries no Node runtime and no source.

# --- Stage 1: build ---
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# --- Stage 2: serve ---
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

# Use 127.0.0.1, not localhost: inside the container "localhost" resolves to ::1
# first, but nginx's `listen 80;` binds IPv4 only, so the check would be refused
# even though the site is serving perfectly.
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
