# Host-built sample-node-site image for T2 load-into-target (D-025).
# Do not docker build this on hub-test-target: vfs cannot pull
# registry-1.docker.io, and the fixture lockfile is scanner-shaped
# (MUTATIONS.md #5) — frozen integrity does not match registry tarballs
# on overlay either. Build on the Hub host, docker load into the target.
FROM node:22-alpine
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.15.4 --activate
COPY package.json pnpm-workspace.yaml ./
COPY packages/server/package.json packages/server/package.json
COPY packages/web/package.json packages/web/package.json
RUN pnpm install --no-lockfile
COPY packages/server/tsconfig.json packages/server/tsconfig.json
COPY packages/server/src packages/server/src
# Fixture has no sr-worker.ts; Engine constructs Worker(./sr-worker.js).
RUN printf '%s\n' \
  'import { parentPort } from "node:worker_threads";' \
  'parentPort?.on("message", () => {});' \
  > packages/server/src/sr-worker.ts
WORKDIR /app/packages/server
RUN mkdir -p /data
ENV NODE_ENV=production
ENV PORT=80
ENV DATA_DIR=/data
EXPOSE 80
# Fixture package.json has no "type":"module"; tsc -p . fails on import.meta.
# tsx runs the real Fastify /healthz (backfill_pct, not the alpine stub).
CMD ["pnpm", "exec", "tsx", "src/index.ts"]
