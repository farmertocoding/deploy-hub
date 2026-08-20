# hub-test-target

Phase 2 T2 image (D-015): Ubuntu, systemd as PID 1, sshd, inner Docker with
`storage-driver=vfs`, and Caddy. Built locally (or multi-arch) — not an
amd64-only pull.

## Build

```bash
docker build -t hub-test-target:local images/hub-test-target
```

## Run

Privileged + host cgroup namespace. **Do not** bind the Hub's Docker socket
into this container — that would make `docker build` run on the Hub (§B1).

```bash
docker run -d --name hub-test-target \
  --privileged --cgroupns=host \
  -p 127.0.0.1::22 \
  hub-test-target:local
```

SSH user is `deploy` (keys only; root login and passwords are off). The T2
fixture installs a one-shot authorized key.

## What this is not

Not T3: no Multipass, no overlay2, no ufw/fail2ban truth test, no reboot.
`jrei/systemd-ubuntu` is banned (no arm64 manifest).
