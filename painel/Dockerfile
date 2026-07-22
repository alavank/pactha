# Painel Executivo (Next.js 16) — build standalone p/ imagem enxuta no Coolify.
# App SEPARADO do frontend operacional; consome a MESMA API do cliente via /api.
# NEXT_PUBLIC_* sao inlined no bundle => precisam vir como build ARG (build-time).
#   Coolify: Dockerfile Location = painel/Dockerfile ; Base Directory = painel
#   Build args:
#     NEXT_PUBLIC_API_URL          = https://painel.<cliente>.com.br/api
#     API_PROXY_TARGET             = http://<host-interno-API>:8000
#     NEXT_PUBLIC_VAPID_PUBLIC_KEY = <chave publica VAPID do cliente>
#     NEXT_PUBLIC_CLIENT_NAME      = Monte Siao
#     NEXT_PUBLIC_CLIENT_UF        = MG
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps --no-audit --no-fund

FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL
ARG API_PROXY_TARGET
ARG NEXT_PUBLIC_VAPID_PUBLIC_KEY
ARG NEXT_PUBLIC_CLIENT_NAME
ARG NEXT_PUBLIC_CLIENT_UF
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    API_PROXY_TARGET=$API_PROXY_TARGET \
    NEXT_PUBLIC_VAPID_PUBLIC_KEY=$NEXT_PUBLIC_VAPID_PUBLIC_KEY \
    NEXT_PUBLIC_CLIENT_NAME=$NEXT_PUBLIC_CLIENT_NAME \
    NEXT_PUBLIC_CLIENT_UF=$NEXT_PUBLIC_CLIENT_UF \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
