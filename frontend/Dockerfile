FROM node:22-alpine AS development
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_AMAP_JS_API_KEY
ARG VITE_AMAP_SECURITY_JS_CODE
ARG VITE_AMAP_CENTER_LNG=118.9000
ARG VITE_AMAP_CENTER_LAT=32.1000
ARG VITE_AMAP_ZOOM=13
RUN npm run build

FROM nginx:1.27-alpine AS production
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
