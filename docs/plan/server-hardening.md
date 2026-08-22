# Ubuntu Server Hardening & Deploy Automation — Rules, Commands, Scripts

For the Ubuntu servers in the **web deploy automation & monitor** fleet. Derived from the reviewed plan (`deploy-system-plan.md` §6.5/§6.6/§7.1) and the 2026-07-30 security round (`plan-addendum-2026-07-30.md` §B/§C). Every rule below is also implemented by the scripts, so you can read-and-type or run — same commands either way (the plan's one-catalog principle).

**UPDATE 2026-08-22 (Phase 2.5 T3):** `harden-ubuntu.sh` is v2026-08-22. Test-only no-mesh bypass for Multipass (never set on a real host): `HUB_TEST_MODE=1` (or true/yes/on) **and** `PROFILE=target` **and** `HUB_T3_UFW_ONLY=1` or `HUB_T3_ALLOW_NO_MESH=1`. Then ufw+fail2ban can still enable without a tailnet. `HUB_T3_SSH_FROM=<ipv4>` is honored only on that same gated path. This path **does not prove HARD-V2**; unset `HUB_TEST_MODE`, `PROFILE=hub`/`intake`, or a lone T3 skip var still refuse the tailscale0-only firewall. `HUB_MESH_IP` remains required (singular IPv4, never `100.64.0.0/10`).

**UPDATE 2026-08-21 (Task 6 fix):** Script provenance & custody (per review3 §Q8). The canonical location of every script below is the **Hub repo under `scripts/`** — `scripts/**` is on the always-human-merged sensitive-path list (build-process §5). Versions as of this update: `harden-ubuntu.sh` v2026-08-22 · `update-cloudflare-ufw.sh` v2026-08-20 · `verify-hardening.sh` v2026-08-20 · `hub-upgrade.sh` v2026-08-22 · `server-watch.sh` v2026-08-20. **Rule: any script change updates this doc in the same change.** These scripts are the **pre-Hub interim implementation of specific catalog entry IDs**: script versions map to catalog entry versions, and each script is retired when the corresponding Hub Beat/provisioner machinery goes live — at which point the provisioner **removes the script cron jobs** so there is no double execution and no double paging.

## The scripts

| Script | Run on | What it does |
|---|---|---|
| `harden-ubuntu.sh` | every server, once (re-runnable) | Full hardening: users, SSH, ufw, fail2ban, auto-updates, sysctl, chrony, Docker, Tailscale. Profiles: `hub` / `target` / `intake` (review3 §O2). `DRY_RUN=1` prints instead of executing. |
| `update-cloudflare-ufw.sh` | target hosts, weekly cron | Refreshes the "443/80 only from Cloudflare" ufw rules from Cloudflare's published lists; aborts safely if the fetch looks wrong. |
| `verify-hardening.sh` | every server, cron/CI/after changes | Read-only pass/fail checklist (drift detection until the Hub's own §6B audit exists). |
| `hub-upgrade.sh` | the Hub host only | Safe upgrade of the Hub itself: drain-check → DB backup → keep previous image → build → migrate → warm restart → smoke test. `--rollback` restores the previous kept image. |
| `server-watch.sh` | every server, cron | Interim fleet alerting (pre-Hub): publishes failures to the ntfy pager channel — delivered with a **distinct per-server ntfy publish token** (review3 §V8/§M3), so a compromised host is identifiable and revocable. |

### Script ↔ catalog id

Scripts are the pre-Hub interim of these catalog ids (Task 5). Script files landed in Task 6.

| Script | Catalog ids |
|---|---|
| `scripts/harden-ubuntu.sh` | ntp-chrony, log-rotation, docker-daemon-json, sshd-dropin, ufw-posture-hub, ufw-posture-target, ufw-posture-intake, fail2ban-ignoreip, caddy |
| `scripts/update-cloudflare-ufw.sh` | ufw-posture-target |
| `scripts/verify-hardening.sh` | check argv of every id above |
| `scripts/hub-upgrade.sh` | C6 Hub self-upgrade |
| `scripts/server-watch.sh` | — |

### Quick start

**UPDATE 2026-08-02 (review3): run order reordered per §V2 — join the mesh FIRST, then harden.** The previous order ran `harden-ubuntu.sh` (default-deny; hub profile allows only `tailscale0`) before `tailscale up` — on a remote fresh server reached over public SSH, enabling that firewall off-mesh cuts the only access path: the §6.6 "sshd -t first" failure class at the firewall layer. So: install + `tailscale up` + verify mesh SSH **first**, then run hardening. `harden-ubuntu.sh` now also encodes this as a guard (mirroring the authorized_keys one): it **refuses the tailscale0-only firewall posture unless `tailscale status` shows the mesh up and the current session (or a verified second path) rides it.**

```bash
# 1. put your SSH public key on the machine first (or the script will refuse
#    to disable password auth — by design):
ssh-copy-id you@server

# 2. copy the scripts, then join the mesh BEFORE hardening (review3 §V2):
sudo tailscale up --ssh=false                      # join your mesh (your own auth key)
ssh you@<tailscale-ip>                             # verify mesh SSH works FIRST

# 3. now harden from a mesh SSH session (the script refuses the
#    tailscale0-only posture unless this session rides the mesh).
#    Ubuntu sudo env_reset drops SSH_CONNECTION — keep the proof:
#      Defaults env_keep += "SSH_CONNECTION SSH_CLIENT SSH_TTY"
#    A real local console (no SSH_*) must set HUB_CONFIRM_LOCAL=1.
sudo PROFILE=target DRY_RUN=1 ./harden-ubuntu.sh   # read what it will do
sudo PROFILE=target ./harden-ubuntu.sh             # do it     (hub host: PROFILE=hub)
sudo PROFILE=target ./verify-hardening.sh          # prove it held

# 4. verify from OUTSIDE (any other network):
nmap -Pn <public-ip>            # hub: nothing open · target: only 80/443, CF-only
ssh root@<public-ip>            # must fail
```

---

## The rules, and why (read-and-type version)

### R1 — Two firewall postures, never one

**Hub host (control plane): zero public inbound ports.** The Hub holds SSH keys and cloud credentials for the whole fleet; an auth-bypass bug in its own web code must be unreachable from the internet (this is the TeamCity CVE-2024-27198 lesson — internet-exposed control planes get owned by URL tricks, not password guessing). Everything — panel, API, Postgres, Redis — arrives over Tailscale only:

```bash
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow in on tailscale0 comment 'tailscale mesh'
sudo ufw --force enable
```

**Target host (serves websites): 443/80 open only to Cloudflare's ranges.** DDoS defense is architectural — attack traffic dies at Cloudflare's edge, and this rule makes bypassing the edge impossible: an attacker who discovers your origin IP hits a closed port.

```bash
# per published range (the script iterates both lists):
sudo ufw allow proto tcp from 173.245.48.0/20 to any port 443 comment 'cloudflare edge'
# keep the list fresh weekly (stale list = blocked users or an open old range):
echo '17 4 * * 1 root /usr/local/sbin/update-cloudflare-ufw.sh >> /var/log/cf-ufw-update.log 2>&1' \
  | sudo tee /etc/cron.d/cloudflare-ufw
```

SSH on targets rides Tailscale too. If you must keep public 22 during migration: `sudo ufw limit 22/tcp` (rate-limited: 6 conn/30s per IP), and delete it when the mesh works.

**UPDATE 2026-08-02 (review3): a third profile — `intake` (per §O2).** The Partner Intake VM was outside every loop ("two firewall postures, never one" — the intake was neither). The `intake` profile = **tailnet member + Cloudflare-Tunnel-published service, no public inbound ports** — verified by the same scripts (`harden-ubuntu.sh PROFILE=intake`, `verify-hardening.sh PROFILE=intake`). The intake VM is **enrolled as a Target** (provisioned by the §7.1 playbook) and **probed externally via its public hostname** (`api.partners.<domain>`).

### R2 — SSH: keys only, no root, validate before reload

```bash
sudo tee /etc/ssh/sshd_config.d/99-hub-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 3
EOF
sudo sshd -t && sudo systemctl reload ssh   # -t FIRST: a typo + reload = locked out
```

Rule inside the rule: **never disable password auth before an authorized_keys file exists** — the script enforces this check for you. Drop-in files under `sshd_config.d/` beat sed-editing the main config: they survive package upgrades cleanly.

### R3 — Brute force meets a jail, but never jail your own Hub

**UPDATE 2026-08-02 (review3): `ignoreip` narrows to the Hub only (per §V1).** The previous `jail.local` whitelisted all of `100.64.0.0/10` — every current and future tailnet device, including future partner-tier targets and any device an attacker adds via the §B8 path, could brute-force SSH un-jailed. §C3 authorizes whitelisting "the Hub's mesh IP" — singular. Now: `harden-ubuntu.sh` takes **`HUB_MESH_IP` as a parameter and whitelists only it**; the /10 line survives only commented-out, marked "only after tailnet ACLs restrict target↔target"; `verify-hardening.sh` checks the narrowed value; the §6B audit will flag any broader `ignoreip`. If the /10 interim is knowingly kept anywhere, it's a `WAIVERS.md` line, not a silent default.

```bash
HUB_MESH_IP=<hub-mesh-ip>   # set in YOUR shell first — the heredoc below expands it
sudo tee /etc/fail2ban/jail.local <<EOF
[sshd]
enabled = true
maxretry = 4
findtime = 10m
bantime = 1h
ignoreip = 127.0.0.1/8 ${HUB_MESH_IP}
# ignoreip = 127.0.0.1/8 100.64.0.0/10   # only after tailnet ACLs restrict target↔target
EOF
sudo systemctl enable --now fail2ban
```

Whitelisting the Hub's mesh IP is the reliability-review fix: the Hub probes every target once a minute over the mesh — without the exclusion, your own monitoring bans your own control plane.

### R4 — Patches apply themselves

```bash
sudo apt install -y unattended-upgrades
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
  | sudo tee /etc/apt/apt.conf.d/20auto-upgrades
```

A missed security patch is the most boring way to lose a server. Nightly security updates, automatic.

### R5 — Kernel network hardening

```bash
sudo tee /etc/sysctl.d/99-hub-hardening.conf <<'EOF'
net.ipv4.tcp_syncookies = 1              # SYN-flood resistance
net.ipv4.conf.all.rp_filter = 1          # anti-spoofing
net.ipv4.conf.all.accept_redirects = 0   # no ICMP-redirect MITM
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
EOF
sudo sysctl --system
```

### R6 — Clocks are a security control

```bash
sudo apt install -y chrony && sudo systemctl enable --now chrony
chronyc tracking     # skew must stay < 2s
```

Skewed clocks silently corrupt TLS validation, traffic-stat buckets, and the attack detector's baselines — the reliability review made NTP a mandatory catalog entry, not a nicety.

### R7 — Docker: local socket only, bounded logs, no fresh privileges

```bash
sudo tee /etc/docker/daemon.json <<'EOF'
{ "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" },
  "live-restore": true,
  "no-new-privileges": true }
EOF
sudo systemctl restart docker
ss -lntp | grep -E ':(2375|2376)\b' && echo "BAD: docker on TCP" || echo "ok"
```

The daemon never listens on TCP (a TCP Docker socket is unauthenticated root). `live-restore` keeps site containers serving through a Docker upgrade — the P2 "sites survive the control plane" invariant at the daemon level. Site containers additionally run non-root, one Docker network per site, with `--memory/--cpus` limits (the Hub's pipeline generates that; it's in the manifest spec).

### R8 — Tailscale from the signed repo, and the account above it is hardened

```bash
# distro package (signed repo) — deliberately not curl|sh:
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/$(lsb_release -cs).noarmor.gpg \
  | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/$(lsb_release -cs).tailscale-keyring.list \
  | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt update && sudo apt install -y tailscale
sudo tailscale up --ssh=false
```

The mesh is the trust anchor for everything, so (addendum §B8): hardware-key 2FA on the SSO account that owns the tailnet, and evaluate tailnet lock in Phase 4 — a compromised Tailscale account must not be able to silently add a device to your network.

### R9 — Deploy safety rules the scripts encode

The safest deploy is the one that is boring and reversible: **never `runserver`** (gunicorn behind Caddy) · immutable image tags, never `:latest` · migrate **before** switching traffic, expand-contract for destructive changes · blue-green cutover with the old container kept stopped for instant rollback · backup **before** migrate, encrypted, off-host · every deploy recorded (who/what/when/log). `hub-upgrade.sh` applies the same discipline to the Hub itself: drain → backup → migrate → warm restart (SIGTERM so Celery tasks checkpoint) → smoke test → `--rollback` restores the previous kept image.

### R10 — Verify from outside, on a schedule

Config-reading is not proof. Weekly (until the Hub's own §6B audit job takes over):

```bash
sudo PROFILE=target /usr/local/sbin/verify-hardening.sh   # on-host checklist
nmap -Pn <public-ip>                                      # from another network
curl -m 5 http://<public-ip>/                             # target: should hang/refuse (CF-only)
```

A firmware reset, a debugging session at 2 a.m., or a package upgrade can silently undo any rule above — drift detection is part of the security model, not an extra.
