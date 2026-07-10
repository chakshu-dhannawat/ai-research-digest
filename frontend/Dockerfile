FROM node:22-slim AS build
ARG HTTP_PROXY=http://proxy.otsuka-shokai.co.jp:8080
ARG HTTPS_PROXY=http://proxy.otsuka-shokai.co.jp:8080
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3737
