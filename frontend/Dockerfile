# Frontend Next.js 16 (PACTHA) — build standalone p/ imagem enxuta no Coolify.
# NEXT_PUBLIC_API_URL e inlined no bundle => precisa vir como build ARG (build-time).
#   Coolify: Dockerfile Location = frontend/Dockerfile ; Base Directory = frontend
#   Build arg: NEXT_PUBLIC_API_URL = https://pactha.alavank.com.br/api
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps --no-audit --no-fund

FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
# Saida standalone (next.config.ts: output: 'standalone')
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
