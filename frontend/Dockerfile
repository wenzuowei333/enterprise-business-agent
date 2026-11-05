FROM node:22-alpine AS build

ARG VITE_EXCEPTION_CENTER_ENABLED=false
ENV VITE_EXCEPTION_CENTER_ENABLED=${VITE_EXCEPTION_CENTER_ENABLED}

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
