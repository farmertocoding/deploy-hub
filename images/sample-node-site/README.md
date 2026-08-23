# sample-node-site (T2 host image)

Host-built Fastify image of `sample-node-site/`. Loaded into `hub-test-target`
with `docker load` — inner dockerd on vfs must not pull `registry-1.docker.io`
(D-025 / leftover Task 7).

## Build

```bash
docker build -f images/sample-node-site/Dockerfile \
  -t sample-node-site:t2 sample-node-site
```

The fixture `pnpm-lock.yaml` is scanner-shaped (MUTATIONS.md #5). This
Dockerfile uses `pnpm install --no-lockfile` on the host overlay.
