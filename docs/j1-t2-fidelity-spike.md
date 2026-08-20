# J-1 — T2 fidelity spike (sshd+systemd container vs Multipass)

**Date:** 2026-08-20 · **Decision:** D-015 · **Host:** Docker Desktop 20.10.17 on
arm64 macOS, cgroup v2. Throwaway containers were deleted after the probe.

§J.1 asked: does an sshd+systemd container faithfully exercise pipeline steps
1–5, or is Multipass needed sooner? The answer is the T2/T3 boundary below.
Nothing from this spike ships in the product — `hub-test-target` is a Phase 2
image, built to this record.

## What pipeline steps 1–5 actually need on the target

Per §8: **build** (docker build on the target, §B1), **ship** (`docker save` /
`docker load`), **migrate** (one-off container), **start green**, **health
check** (`/healthz` `ready`). All five are SSH + a working dockerd. systemd is
for the provisioner catalog (Q8: `harden-ubuntu.sh` twice), not for the
pipeline itself. ufw/fail2ban are the §G T3 truth test, already named.

## Probe results (this machine)

| Probe | Result |
|---|---|
| Alpine + OpenSSH, TCP 2222 | SSH-2.0 banner received. sshd-in-container is real. |
| `docker:20.10-dind` privileged, inner `hello-world` | **ok.** Inner Storage Driver overlay2. Nested docker *as a dind image* works. |
| `jrei/systemd-ubuntu:22.04` | **no arm64 manifest.** Do not pin an amd64-only base for `hub-test-target`. |
| Ubuntu 22.04, privileged, cgroupns=host, systemd as PID 1 | `systemctl is-system-running` → `running`. |
| `apt install openssh-server` + `sshd -t` + drop-in `PasswordAuthentication no` / `PermitRootLogin no` + `systemctl enable --now ssh` | `sshd_t_ok`, `ssh` **active**. HARD-R2 is T2-shaped. |
| `apt install docker.io` (29.1.3) default overlay inside that systemd container | daemon **active**; `docker run` / `docker build` fail: `overlay … invalid argument` (overlay-on-overlay on Docker Desktop). |
| Same dockerd with `"storage-driver": "vfs"` | **`docker build` + `docker run` succeed** (`CMD echo built-inside` printed). |
| `ufw --force enable` | reports `Status: active`. Classic false-green — a container's ufw is not a host firewall. |
| `systemctl enable --now fail2ban` | unit enable succeeded; `is-active` **failed**; no socket. |

## The boundary

**T2 (`hub-test-target`, Phase 2):** Ubuntu + systemd as PID 1 + sshd + docker
with **vfs** (or a dind data-root that is not overlay-on-overlay). Privileged +
`--cgroupns=host`. Multi-arch or locally built — not an amd64-only pull.

This container *does* faithfully exercise:

- fabric / real sshd / SFTP (the Transport integration seam)
- `sshd -t`, drop-ins, `systemctl` for ssh and other units
- pipeline steps 1–5 as a protocol (build on the target, load, start, poll
  `/healthz`) via inner docker on vfs
- run-twice idempotency of those steps (mutating Transport calls = [])

It does **not** faithfully exercise, and must not be asked to:

- host firewall / fail2ban as the §6B truth test (ufw lies; fail2ban did not
  run) — already T3 in §G
- overlay2 as the target's storage driver
- reboot, NTP/chrony host clock, sysctl that is a host kernel
- a public bind of 80/443 on a real NIC

**T3 (Multipass locally, QEMU/KVM on CI, Phase 2.5):** the overlay2 deploy, the
ufw/fail2ban truth test, reboot, nightly provision→deploy→rollback.

**Multipass is not needed sooner.** Phase 2 can start on T2. Phase 2.5 is still
where T3 is assembled. Binding the Hub's `docker.sock` into the target to skip
inner dockerd would make step 1 run on the Hub and is a §B1 false-green — do
not.

## What this does not keep

The `j1-ubuntu-systemd:spike` image and the three probe containers were
removed. No Dockerfile lands here; Phase 2's design note writes `hub-test-target`
to this recipe.
