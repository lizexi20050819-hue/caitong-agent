# ===== 财通Agent 前端 Dockerfile =====
# 阶段 1：构建 Vue 应用

FROM node:22-alpine AS build
WORKDIR /app
RUN npm config set registry https://registry.npmmirror.com
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# 阶段 2：Nginx 托管静态文件 + 反向代理 API

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
