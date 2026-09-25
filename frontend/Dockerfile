# Orbit Frontend — Next.js standalone 生产镜像
# 多阶段构建：builder 装依赖并编译，runner 只保留运行时产物

# ── 构建阶段 ──
FROM node:20-alpine AS builder

WORKDIR /app

# 依赖层缓存：仅 package 变化时才重装
COPY package.json package-lock.json* ./

# 构建加速（可选）：国内环境传 --build-arg NPM_REGISTRY=...；
# 默认走官方源，CI 与海外构建行为完全不变。
ARG NPM_REGISTRY=""
RUN npm config set registry "${NPM_REGISTRY:-https://registry.npmjs.org}" \
    && npm ci

# NEXT_PUBLIC_* 在构建时内联进产物，必须在 build 前注入
# 该地址由浏览器直接访问，需填宿主机可达地址（非容器内主机名）
ARG NEXT_PUBLIC_API_URL=http://localhost:8001
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

COPY . .
RUN npm run build

# ── 运行阶段 ──
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 orbit \
    && adduser --system --uid 1001 --ingroup orbit orbit

# standalone 产物自带精简 node_modules，无需再安装依赖
COPY --from=builder --chown=orbit:orbit /app/public ./public
COPY --from=builder --chown=orbit:orbit /app/.next/standalone ./
COPY --from=builder --chown=orbit:orbit /app/.next/static ./.next/static

USER orbit

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD node -e "require('http').get('http://127.0.0.1:3000',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
