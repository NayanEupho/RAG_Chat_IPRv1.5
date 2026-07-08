# Stage 1: Dependencies
FROM oven/bun:1 AS deps
WORKDIR /app

# Admin_Dashboard currently has no committed bun.lock, so install from package.json.
# If a bun.lock is added later, switch this to COPY package.json bun.lock ./ and
# bun install --frozen-lockfile for fully pinned builds.
COPY package.json ./
RUN bun install

# Stage 2: Builder
FROM deps AS builder
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY . .
RUN bun run build

# Stage 3: Runner
FROM oven/bun:1-slim AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0
# Backend upstream used by /api/admin-backend/[...path].
# Override this in compose/deployment if the backend service has a different name.
ENV ADMIN_BACKEND_UPSTREAM=http://Askme-admin-backend:8000

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3001

CMD ["bun", "server.js"]
