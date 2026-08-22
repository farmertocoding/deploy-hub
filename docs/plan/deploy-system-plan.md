# Deploy Automation & Monitoring System — Master Plan

**Project:** web deploy automation & monitor
**Stack:** Python / Django (backend) · React (frontend) · Celery (jobs)
**Targets:** Your own computer/server · AWS · Microsoft Azure
**Date:** 2026-07-21

> **Build copy note (docs/plan):** §1–§5 and the section markers are verbatim from the
> project doc; §6–§13 are FAITHFULLY CONDENSED (every rule, decision, and UPDATE marker
> preserved; explanatory prose shortened). The CANONICAL full text lives in the Claude
> project ("web deploy automation & monitor" → claude/deploy-system-plan.md) — cite and
> hash registry entries against section IDs, and consult the project doc before relying
> on §6+ wording verbatim. The Scribe replaces this with a verbatim sync at Phase 1 exit.
> Authority order: review3 addendum > scanner addendum > 07-30 addendum > this doc.

---

## 1. What you are really building

The system you described has a well-known shape in industry: a **deployment control plane** — a private, self-hosted "mini-Heroku" that you operate yourself. It is one Django + React application (the "Hub") that manages many *other* applications (your "Sites"). Everything you asked for maps onto five engines inside that Hub:

| Your requirement | Engine in this plan |
|---|---|
| "Select a path to my project… check production settings… ask me questions… check production ready" | **Project Scanner & Readiness Wizard** (§5) |
| "System setup" | **Target Provisioner** — prepares your machine / AWS / Azure hosts (§7) |
| "Security check" | **Security Suite** — pre-deploy, infra, and post-deploy checks (§6) |
| "Make website live… automatically setup DNS… on designated machine or AWS or Azure" | **Go-Live Pipeline** — DNS + TLS + routing automation (§8) |
| "Interface to monitor web traffic of each site" | **Monitoring Dashboard** (§9) |
| "Advice of best production server deploy practice" | Baked into the checks, plus §10 written out explicitly |
| "Prevent attack like DDoS from the beginning" | **DDoS & Abuse Defense** — five layers, edge-first (§6.5) |
| "Best firewall & system security advice, showing what to type in the command line" | **Hardening Advisor** — gap-based, copy-paste commands with explanations (§6.6) |
| "Live map of all instances on the network" | **Live Network Map** — real-time topology graph with load, traffic, and events (§9.6.1) |
| "Show best deploy network — this app separated from other apps/machines/networks" | **Topology Advisor** — Hub isolation, blast-radius tiers, segmentation rules (§9.6.2) |
| "Suggestions or automation of local router settings" | **Router Advisor** — model-tailored steps, safe automation, outside-in verification (§7.1.1) |
| "Upload SSH keys / set up HTTPS with my own keys" | **Keys & Certificates Manager** — web vault for SSH keys and custom TLS certs (§7.4) |
| "All frontend and backend audit input and warn on wrong input" | **Input Validation & Warning Standard** — dual-layer, schema-shared, errors block / warnings ask (§4.5) |
| "System panel should be real-time WebSocket update" | **Real-Time Panel Standard** — one multiplexed socket, snapshot-then-stream, every panel live (§3.5) |
| "Encryption so data is useless even if a hacker steals it" | **Data Encryption Architecture** — envelope encryption, key hierarchy, encrypted disks & backups (§6.9) |
| "2FA required for panel login, with Yubico API support" | **Hardware-first 2FA** — WebAuthn/FIDO2, mandatory (§6.10; YubiOTP dropped 2026-07-30) |
| "Deploy to machines on the local network, or SSH deploy cross-network" | **Target enrollment modes** — LAN enroll, Tailscale mesh, direct SSH, jump host (§7.1.0) |
| "Deploy new instance when local machine is about to overload" | **Overflow Auto-Scaling** — attack-gated burst to AWS/Azure/other machine (§9.5) |
| "Take API calls or MCP functions — other website's client chooses a site, this system auto-deploys" *(added 2026-07-30)* | **Partner Deploy API & MCP Server** — public intake + pull model, partner keys, template catalog, Cloudflare for SaaS domains (addendum §K) |

### 1.5 What a deployment control plane *should be* — five principles (design-review upgrade)

**P1 — Declarative desired state + a reconciliation loop (the biggest upgrade).** The DB stores **desired state** (site X, image tag Y, on targets A+B, domain Z, hardening profile H), and a **reconciler** — a Celery Beat job every 1–2 minutes — compares desired against *observed* state (probed containers, actual DNS records, actual Caddy routes, actual firewall rules) and converges any difference: a container that died at 3 a.m. is restarted, a DNS record someone deleted is re-created, a Caddy route lost to a host reboot is re-applied — without you noticing, and logged when it happens. Under this model a "deploy" is just *"update desired state; let the reconciler converge"*, and the §6B/§6.6/§7.1.1 drift audits become one loop with different probes. **The system returns to correct on its own.**

**P2 — Control plane and data plane are separable: sites must keep serving if the Hub is off.** Every site-serving dependency must live on the target, not the Hub. DNS records are static once set; Caddy config **persisted to disk on the host** (autosave so admin-API changes survive reboot without the Hub); access logs buffer on-host; containers restart via Docker `--restart unless-stopped`. What you lose while the Hub is down is monitoring, scaling, and deploys — never uptime. Verified by a standing chaos test: stop the Hub for 24h, confirm every site unaffected.

**P3 — Every operation idempotent, resumable, and serialized.** Each `Deployment` is a **persisted state machine** (step, status, artifacts per step) so a crashed deploy resumes from its last completed step or aborts cleanly. Per-site and per-host **locks** serialize operations. All playbook steps are idempotent (safe to run twice), which P1's reconciler also depends on.

**P4 — One source of truth, everything auditable and diffable.** The Hub DB is the only authority; no configuration lives *only* on a host. Every generated artifact (Dockerfile, env file, Caddy route, DNS record set, firewall rules) is **snapshotted per deployment** — "what changed between deploy 41 and 42" is a diff, and rollback is re-applying a known artifact set.

**P5 — Fail safe, small blast radius, always a manual path.** Propose-mode scaling, hard budget caps, default-deny firewalls, warnings that must be acknowledged (§4.5), plus **break-glass runbooks** — a per-site markdown runbook (where it runs, current image tags, exact manual rollback/restart/DNS commands in §6.6 style), stored on the target itself.

The single most important design idea: **make every target look the same** — "a Linux host with Docker, reachable over SSH." One deployment system, three *provisioners* that produce identical hosts.

---

## 2. Key decisions (with recommendations)

| # | Decision | Recommendation | Why |
|---|---|---|---|
| 1 | App packaging | **Docker containers** | Same artifact everywhere; rollback = previous image tag. |
| 2 | Cloud pattern | **Plain VMs (EC2 / Azure VM) with Docker**, not ECS/App Service/Fargate | Uniformity; one deploy path. |
| 3 | Hub → hosts | **Push over SSH** (paramiko/fabric from Celery workers) | No agent to build/secure on day one. |
| 4 | Reverse proxy | **Caddy** (over Nginx) | Auto-LE TLS, JSON admin API, structured JSON access logs. |
| 5 | DNS automation | **Provider adapters: Cloudflare (primary), Route 53, Azure DNS** | One `DnsProvider` interface; Cloudflare default NS for all domains. |
| 6 | Cloud provisioning | **Cloud SDKs directly (boto3, azure-mgmt); Pulumi later if it grows** | Raw SDK calls are simpler for "1 VM + ports + IP". |
| 7 | Job execution | **Celery + Redis**, live logs via Django Channels | Deploys survive page reloads, stream logs. |
| 8 | Hub database | **PostgreSQL** (SQLite acceptable for first mockup) | Time-series-ish aggregates. |
| 9 | Frontend | **React SPA (Vite) + DRF API** — session-cookie auth + CSRF header, **not JWT** (UPDATE 2026-07-30; addendum §A1); WebSocket rides the same session; every subscribe passes `authorize_topic()` | — |
| 10 | Traffic analytics | **Caddy JSON logs → Hub → Postgres aggregates → React charts** | Self-contained, private. |
| 11 | Secrets | **Env files generated by Hub, vault-encrypted (§6.9), pushed at deploy** | Central; upgrade path: SSM/Key Vault pull. |
| 12 | Zero-downtime | **Blue-green at container level** via Caddy upstream switch | No orchestrator needed. |
| 13 | DDoS / edge | **Cloudflare proxy in front of every site by default** (Tunnel for home target); origin firewalled to CF IPs only | Only the edge can absorb volumetric attacks (§6.5). |
| 14 | Overflow scaling | **Reactive, attack-gated auto-scaling** — composition of provisioner + pipeline + DNS (§9.5) | Attack-gate prevents auto-billing. |

> Per your preference: mockup-first — plain readable Python, no premature optimization.

---

## 3. Architecture overview

Hub (React UI · DRF API · Channels WS · Celery workers · Beat · Postgres · Redis) —SSH→ targets (own machine / EC2 / Azure VM, each running Caddy + site containers), —API→ AWS/Azure/Cloudflare. Targets return access logs to Beat ingest.

**Flow of a deployment:** pick project path + target → Scanner runs, Wizard asks → Hub generates a *deployment manifest* (Dockerfile, env file, Caddy route) → Celery job builds (on target, §B1), ships, migrates, starts blue-green, wires DNS + TLS, runs smoke tests → dashboard shows live traffic.

## 3.5 Real-Time Panel Standard — WebSocket everywhere

**One socket, many topics.** The browser holds a *single* multiplexed Channels connection; the client subscribes to topics for whatever is on screen (`deploy.{id}.log`, `host.{id}.metrics`, `site.{id}.traffic`, `checks.{target}`, `scaling.episodes`, `map.graph`, `alerts`) and unsubscribes on navigation. Every producer publishes via one `publish(topic, event)` helper.

**Reconnect honestly.** Every event carries a per-topic monotonic sequence number; on reconnect the client refetches the REST snapshot for visible panels before resuming the stream (snapshot-then-stream — one code path for load and resume). A quiet "reconnecting…" pill; degraded 10s REST polling with a visible note if WS is unavailable.

**Scale note:** single-admin panel — one socket, dozens of topics, tens of events/sec worst case. Channels + Redis, no Kafka. The Phase 0 demo job proves the full path (Celery → Redis → Channels → React).

---

## 4. Data model sketch (Hub)

`NetworkZone` · `Target` (zone FK, kind, host, ssh_user, ssh_key_ref, lifecycle: permanent|ephemeral, status) · `Project` (git_url/source_path, framework_detected, scan_report) · `Site` (project FK, domain, tier: prod|staging|experiment, env_vars_encrypted, desired_state, scale_ready; **UPDATE 2026-08-02 (review3 §M4): + `exposure ∈ {public, mesh_only}`**; **review3 §N1/§N8: + `deploy_strategy: blue_green|recreate`, `deploy_policy: auto|confirm|windowed`**) · `SiteInstance` (site FK, target FK, role, state, internal_port) · `ScalePolicy` · `HostMetric` · `SshKey` · `TlsCertificate` · `Deployment` · `CheckRun` · `DnsRecord` · `TrafficStat` · `UptimeEvent`. **UPDATE 2026-08-02 (review3 §N2/§N5/§N6):** the manifest/Site additionally gain `liveness_path`, `readiness_path`, `warmup_timeout_s`, `data_staleness_threshold` (per-feed), a **volumes list** (name, container path, backup policy), `backup_unit` kinds, and nullable `jobs_image`.

## 4.5 Input Validation & Warning Standard

**Backend is the source of truth.** Every API endpoint validates through DRF serializers; failures return HTTP 400 with `{field: [{code, message, hint}]}`.

**Frontend mirrors it automatically, not manually.** drf-spectacular → OpenAPI → generated TypeScript client + zod schemas; react-hook-form + those schemas validate as the user types. Hand-written duplicate validation rules are banned.

**Errors block, warnings ask.** Errors = impossible input (won't submit, 400). Warnings = legal-but-suspicious (`DEBUG=True` in prod env, `*` in ALLOWED_HOSTS, passphrase-less SSH key for prod, NS mismatch) — amber inline, require explicit "I understand, continue" via the `confirm_warnings` flag (first call returns warnings; second call acknowledges).

**Domain-specific validators, checked deeply:** domains (syntax + live DNS/account checks), IPs/CIDRs, ports, file paths, env names/values (shell metacharacters, secret-entropy), PEM material, cron expressions, instance sizes. Deep checks async server-side ("verifying domain…").

**Validation is also a security boundary:** ① everything touching a shell is **argument lists, never interpolated strings** (file contents via SFTP, not heredocs); ② rejected inputs are audit-logged with source IP — repeated failures feed throttle/fail2ban machinery. SSRF guard per addendum §B10.

**The scanner preaches it too:** matching checks for deployed apps (raw request data without serializers, raw SQL strings, `mark_safe` on user input, missing CSRF).

---

## 5. Project Scanner & Production-Readiness Wizard

### 5.1 Scan phase (automatic, read-only)

**Detection.** Find `manage.py` → Django; `package.json` with react → frontend; record Python/Django versions, dependency files. **UPDATE 2026-08-02:** the scanner is now modular (framework scanner modules; django + node-ts) — see plan-addendum-2026-08-02-scanner-node-ts.md, as patched by plan-addendum-2026-08-02-review3.md (execution-placement rule §M1: executing checks never run on the Hub).

**Django production checks:** `DEBUG` False in prod settings; settings split or env-driven (offer restructure otherwise) · `SECRET_KEY` from env; git history scanned for leaks · `ALLOWED_HOSTS` set · SQLite flagged → Postgres; env-driven credentials · `STATIC_ROOT` + WhiteNoise/CDN; `collectstatic` clean · `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, `X_FRAME_OPTIONS`, `SECURE_PROXY_SSL_HEADER` · `CSRF_TRUSTED_ORIGINS` + CORS config · `makemigrations --check`; pending migrations counted · email/cache/logging config present · pinned requirements; gunicorn/uvicorn present.

**Frontend checks:** production build succeeds, API base URL env-driven, `npm audit` summary. **Hygiene checks:** secrets not committed (gitleaks), `.gitignore` sane, tests exist and pass (advisory), Dockerfile present or generated. *(Build/image verification moved off the scan phase per review3 §M1.)*

### 5.2 Wizard phase (interactive Q&A)

**UPDATE 2026-08-02:** scanner modules contribute their own wizard questions (scanner addendum §S3); the base Django set: ① domain ② target (provision if needed) ③ database choice ④ values for every required env var (auto-extracted) ⑤ fix-it prompts with diffs ⑥ workers/Celery/scheduled jobs.

### 5.3 Verdict

**Production Readiness Report**, three tiers: **Blockers** (won't deploy), **Warnings** (deploys with confirmation), **Advice**. Stored on the `Project`, re-run every deploy, diffed between runs.

---

## 6. Security Suite

**A. Pre-deploy (code & dependencies):** pip-audit, npm audit, bandit, gitleaks, Django deploy checklist. Critical CVE or leaked secret = Blocker. **UPDATE 2026-08-02:** `pnpm audit` added for node projects (modular scanner); scan-phase execution sandboxed off the Hub per review3 §M1.

**B. Host hardening (infra):** SSH key-only, no root, fail2ban · firewall parity (only 22/80/443; verified by external port scan, not config reading) · unattended upgrades · Docker daemon not on TCP; non-root containers · cloud SG/NSG audited via API; least-privilege IAM.

**C. Post-deploy & continuous (runtime):** HTTPS verification + expiry monitoring — **UPDATE 2026-08-02 (superseded):** thresholds owned by alert-protocol.md §2 per review3 §V9 (uploaded 45/21/7 d = P3/P2/P1; auto-renewed 7/1 d = P2/P1) · security-header check · uptime ping (1–5 min) · log-based alerts (5xx spikes, 404 probing, brute force) · email first.

Each run stores a `CheckRun`; each site shows a security score/badge.

## 6.5 DDoS & abuse defense — five layers

**L1 Edge absorption:** every site proxied through Cloudflare by default (orange cloud); free tier gives L3/L4 mitigation, WAF, bot fight, caching, origin-IP hiding — on all three target kinds. **L2 Origin lockdown:** 80/443 accept only Cloudflare's published ranges (weekly-refreshed); SSH via Tailscale; no origin-IP leakage; **Cloudflare Tunnel is the default for the home target** (zero inbound ports, CGNAT-proof). **L3 Proxy throttles (Caddy):** per-IP rate limits, body caps, timeouts, connection limits — generated into every route. **L4 App throttles (Django):** DRF throttles on auth/expensive endpoints, pagination, caching — with matching scanner checks. **L5 Detect & auto-respond:** z-score attack detector on TrafficStat → playbook: Under-Attack mode via API → edge IP/ASN bans → notify → auto-relax. **Cost protection:** budget alerts; the §9.5 scaler is hard-gated by the attack detector — attack-shaped load triggers mitigation, never provisioning.

## 6.6 Hardening Advisor — exact commands, shown and explained

**One catalog, two consumers:** versioned command catalog (check, fix commands per OS, explanation, risk note, rollback); the provisioner executes entries, the Advisor UI renders the same entries copy-paste. **Gap-based:** probe actual state over SSH, advise only the gaps, re-run shows the list shrinking. Example blocks: default-deny ufw + CF-ranges 443 + `ufw limit 22` · sshd keys-only with `sshd -t` first · fail2ban · unattended-upgrades · sysctl hardening. **Cloud parity:** same findings as `aws ec2`/`az network` commands. **Three execution modes per target:** Show-only / Approve-and-run (default) / Auto (with audit log). **Drift watch:** weekly §6B audit reuses the probes; under P1 the reconciler reverts drift in auto mode.

## 6.8 Threat Model

| Attacker | Path | Primary defenses |
|---|---|---|
| Internet attacker | Floods, scans, brute force | §6.5 layers; §6C; §4.5 throttles |
| Compromised site container | RCE → pivot | Per-site Docker networks; non-root; tier separation; mesh ACLs; no SSH keys on targets |
| Compromised target host | Escape / stolen host | Blast radius = that host's tier; CF-only firewall; **SSH host-key pinning** (verified strictly; mismatch = refused + alert) |
| Stolen admin credential / laptop | Log into Hub | Tailscale-only + **mandatory second factor** + short sessions + step-up re-auth (addendum §B6: session TTLs, workstation row, anomaly alerts load-bearing) |
| Supply chain | Malicious dependency/base image | pip/npm audit; **digest-pinned base images**; **Trivy scan per build** (critical = Blocker); lockfiles enforced |
| Hub compromise (worst case) | Owns control plane | No public exposure; vault master-key discipline (never in DB/backups); anomaly alerts; audit trail (off-host per addendum §B3) |

*(Addendum additions: alerting-channel row (review3 §M3), financial/broker credentials row (review3 §M4), partner rows (§K7), tunnel credential, Tailscale account (§B8).)*

### 6.9 Data Encryption Architecture — stolen data must be useless data

**Envelope encryption with a key hierarchy:** every secret gets its own fresh AES-256-GCM **DEK** per write; DEKs wrapped by a **KEK**; AAD binds record id/type. One `EncryptedField`/vault service code path. **UPDATE 2026-07-30:** default KEK placement = **③ cloud KMS (AWS KMS)**; ② YubiKey challenge-response for offline homelab; ① keyfile = dev/test only (addendum §A3). **Data classification:** Secret (field-level, write-only) / Sensitive (DB/disk/transport controls) / Operational (plain). **Other theft paths:** LUKS/encrypted disks on Hub and targets; backups client-side encrypted (age/restic) with a dedicated key, KEK never in backups; TLS everywhere; secrets never in logs/task args/frontend (log scrubber asserts in CI). **Push vs pull recorded:** push is the Phase-1 trade-off; SSM/Key Vault pull is the prod-tier upgrade (Phase 5). **Compromise drill:** new KEK → re-wrap → rotate downstream credentials → audit review.

### 6.10 Two-Factor Login — required, hardware-key first

> **UPDATE 2026-07-30 (research-backed reversal):** the YubiOTP/YubiCloud path is **dropped** (YubiCloud maintenance-mode; see addendum §A2). YubiKeys serve as **WebAuthn security keys** only; TOTP is the fallback second factor. Short session TTLs + hardware step-up on dangerous actions are load-bearing (CircleCI lesson).

**2FA is mandatory:** enrollment at first login; session unusable until done. Primary: WebAuthn/FIDO2 via `django-otp-webauthn`; phishing-resistant, offline-capable. **Resilience rules:** register two hardware keys; hashed one-time recovery codes; TOTP only as explicit fallback. **Step-up:** key export, target delete, auto-mode changes, KEK ops re-prompt for hardware touch. **Watcher resilience:** dead-man's switch (healthchecks.io) · nightly encrypted Hub DB dump + quarterly restore drill · safe test mode (LE staging, test zone, dry-run) · Celery queue isolation (deploys/probes/control).

---

## 7. Target Provisioner

### 7.1 Own computer / any Linux box
Idempotent fabric playbook from the §6.6 catalog: deploy user + SSH key → apt update + unattended-upgrades → Docker + compose → Caddy (admin API on localhost) → firewall per §6.5 L2 → fail2ban → `/srv/sites/` → register + §6B check. Home target default = **Cloudflare Tunnel**; fallback = static LAN IP + port-forward + dynamic-DNS job.

### 7.1.0 Enrolling targets: same-LAN and cross-network SSH
LAN: discovered/manual host → "Enroll as target" → provision over LAN SSH, pin host key; DHCP-reservation warning. Cross-network, ranked: ① **Tailscale mesh (default)** — pre-auth key enrollment, no public 22, mesh ACLs; ② direct hardened SSH (amber); ③ jump host. Pipeline is byte-identical in all modes. Slow links flip to registry-based shipping.

### 7.1.0a Reference design: a two-network fleet
Two zones (e.g. home/office), Hub on its own small machine/VM, tailnet joins all. Per-server enrollment = 2-minute bootstrap (tailscale up with tagged pre-auth key) → provision → green on map. Placement rules: app near its DB (cross-zone pairs flagged amber with real latency); two zones = failover gift for scale-ready prod sites; zone-aware overflow (other zone's idle server before cloud); inter-zone ACLs default-deny (only the Hub spans zones). Zone-level monitoring distinguishes host-down from zone-down; mesh health probed.

### 7.1.1 Local Router Advisor
Detect gateway, tailor steps per model. Tunnel mode: verify *nothing* forwarded. Fallback: DHCP reservation + 80/443 forwards only. Hygiene: admin password, WAN admin off, WPS off, **UPnP off**, firmware, DNS resolvers. Segmentation → VLAN/DMZ steps. Automation line: UPnP mapping opt-in bootstrap only; DDNS repointing; **outside-in verification** of everything; checks join the weekly drift audit. *(Roadmap: Phase 7 per addendum §E9.)*

### 7.2 AWS / Azure
Identical end state: keypair/SG (or NSG) → Ubuntu VM → static IP → same §7.1 playbook → register. Everything downstream has zero cloud-specific code.

### 7.3 Cloud credentials
Encrypted in the Hub; dedicated least-privilege IAM user/service principal; §6B audits scope.

### 7.4 Keys & Certificates Manager
Vault page under §6.9 encryption, write-only after save, every use audited. **SSH keys:** generate in Hub (preferred; private key never travels) or upload existing; per-target assignment; public-key deployment + one-click rotation playbook; stale-key flagging. **TLS certificates:** default = automatic (§8 step 7); manual path for OV/EV/wildcard/Origin/internal-CA certs — validated on upload (key match, chain, SANs, expiry), pushed to Caddy, expiry-watched with earlier thresholds; per-site `auto`/`uploaded` mode. Cloud API credentials live in the same vault.

---

## 8. Go-Live Pipeline

Persisted state machine (P3), artifacts snapshotted (P4), per-site/host locks:

1. **Build** — generate/refresh Dockerfile, tag `site:<git-sha>`. **UPDATE 2026-07-30 (security-critical):** builds run **on the deployment target** (or dedicated builder), never on the Hub (§B1); `npm ci` / `pip install --require-hashes`.
2. **Ship** — `docker save | ssh docker load`; registry later.
3. **Migrate** — one-off container, `--check` first, backup before destructive; **expand-contract** rule; scanner flags destructive-with-code-change.
4. **Start (green)** — new container alongside old, fresh internal port, env pushed this deploy. *(Recreate strategy per review3 §N1 for local-state sites: stop old → start new → wait ready → route.)*
5. **Health check** — poll `/healthz` until healthy or timeout → rollback. **UPDATE 2026-08-02 (review3 §N2):** gates on `ready` with per-site `warmup_timeout_s`; liveness/readiness/staleness are three modeled things.
6. **DNS** — provider adapter upsert, **proxied by default**; Tunnel-mode = CNAME to tunnel; NS-delegation UI + propagation polling. *(mesh_only sites skip this step — review3 §M4.)*
7. **Route + TLS** — Caddy admin API route switch. **UPDATE 2026-07-30 (security-critical):** no DNS tokens on targets (§B2): proxied sites get **Cloudflare Origin Certificates**; unproxied get Hub-central DNS-01 with pushed certs; SSL mode Full (strict).
8. **Smoke test** — external HTTPS request: 200, cert, headers, timing. *(+ wss:// substep for ws sites per review3 §Q7.)*
9. **Cutover complete** — old container stopped after grace (kept for instant rollback); **Rollback button**; migrations rollback manual by design.

---

## 9. Monitoring Dashboard

**Collection:** Caddy JSON logs pulled per minute over SSH (collector contract per addendum §C3) → `TrafficStat` rollups (minute→hour→day). **Per-site view:** req/min, bandwidth, status breakdown, top paths/referrers/IPs, approx uniques, latency percentiles, cert expiry, deploys, uptime bar, security score. **Fleet view:** site cards (up/down, sparkline, error badge, target, deploy/rollback) + host cards (CPU/RAM/disk). *(ws-class sites: card primary metric = last-tick age + connection count — review3 §O3.)* **Alerts:** per alert-protocol.md.

## 9.5 Overflow Auto-Scaling
Sustained-pressure detection (§9.5.1) → **attack gate** (§9.5.2 — attack-shaped load never scales) → cheap remediations first (cache, workers) → scale-out playbook (provision ephemeral → deploy same image → join DNS round-robin behind CF; Tunnel replicas for home) → notify with cost estimate (`propose` default; `max_instances` + budget caps hard) → scale-in with cooldown + reaper for orphans → **scale-ready prerequisite** (§9.5.6: shared DB over mesh, object-storage media, shared sessions/broker, no local writes; failing sites marked single-instance-only). Deliberately burst overflow, not web-scale. *(Phase 6, post-v1 per addendum §E9.)*

## 9.6 Live Network Map & Topology Advisor
**Map:** zones → hosts → containers, Cloudflare edge nodes, Hub as distinct node; solid public paths vs dashed mesh paths; live colors/thickness from metrics; events animate; optional LAN discovery ghosts. **Advisor rules:** r1 **Hub isolation** (own host, no public exposure — critical finding + one-click migration); r2 blast-radius tiers; r3 per-site Docker networks (verified by inspection); r4 DB separation (mesh-only); r5 home-LAN segmentation; r6 cloud segmentation parity; r7 mesh least-privilege ACLs from declared edges; r8 SPOF watch. Score + drift re-evaluated on every graph change.

---

## 10. Production best-practices baked in
gunicorn `2×CPU+1` behind Caddy, never runserver, `/healthz` required · twelve-factor env config · Postgres + nightly off-host `pg_dump` with monthly tested restore + `CONN_MAX_AGE` · WhiteNoise hashed static; media on object storage · immutable tags, migrate-before-switch, blue-green, keep last 3 images · JSON logs to stdout; Sentry offered · §6 security defaults; never SSH root; monthly dependency report · every deploy recorded; anything done twice becomes a Hub feature.

---

## 11. Build roadmap (phased, mockup-first)

> **UPDATE 2026-07-30:** superseded by the revised roadmap in `plan-addendum-2026-07-30.md` §I (golden-path spike first, WebAuthn → Phase 4, Router Advisor → Phase 7, webhook→polling per review3 §M2, adopt-existing-site added, Phase 6 gated post-v1) and by per-phase exit gates in `build-process.md`.

**Phase 0 — Skeleton (weekend):** compose stack (queue split), login + second factor, demo Celery job streaming fake logs over Channels, §4.5 pipeline on the first form. **Phase 1 — Scanner & Wizard (1–2 weeks):** §5 complete; CLI parity. **UPDATE 2026-08-02:** Phase 1 = "scanner modules: django + node-ts" with the `sample-node-site/` fixture; cost per review3 §V10. **Phase 2 — Deploy to own machine.** **Phase 3 — DNS automation + monitoring + map v1.** **Phase 3b — adopt-existing-site, app-log viewer, scheduled-jobs UI, first-run checklist, backup/restore surface, Hub-central DNS-01 (D-032/D-044).** **Phase 4 — Security suite.** **Phase 5 — AWS, then Azure.** **Phase 6 — Overflow auto-scaling.** **Phase 7 — Polish.**

---

## 12. Risks & honest caveats

The Hub is a crown jewel (Tailscale-only, own host). Home-hosting: ISP port blocks / rotating IPs → Tunnel mode. DDoS realism: free CF tier covers most; paid tiers are a billing change, not a redesign. LE rate limits → staging endpoint in test mode. Scope discipline: resist rebuilding Kubernetes. DNS propagation: wait-and-resume. Migrations riskiest: backup-before-migrate non-negotiable.

## 12.4 Deep-research record (2026-07-21)
24-source pass, adversarial verification (23/25 claims confirmed; full record in `research-control-plane-security.md`). §6.9 envelope design and §6.8 Hub-as-production-infrastructure confirmed; KEK ladder, library choices, backup-access monitoring, push-vs-pull trade-off adopted; competitor-matrix claims refuted (PaaS-baseline question later answered in round 2 §H). Parked leads: push-to-deploy, preview envs, scheduled-jobs UI, backup/restore UI (all later adopted in the 07-30 round).

## 12.5 Design-review record (2026-07-21)
Material findings folded in: imperative→declarative reconciler (P1); Caddy autosave (P2); crash-recovery state machine + locks (P3); artifact snapshots (P4); break-glass runbooks (P5); host-key pinning; 2FA; master-key-outside-backups; dead-man's switch; Hub DR; digest pinning + Trivy; expand-contract; queue isolation; safe test mode. Watch-list: Cloudflare vendor dependency (exit kept possible), caddy-ratelimit custom build, Channels scale if multi-admin, Postgres time-series growth.

## 12.6 Second review record (2026-07-30)
10-agent pass: 55 findings (8 critical) all resolved or parked in `plan-addendum-2026-07-30.md` (the authoritative patch layer). Headlines: builds off-Hub; audit off-host; Redis in crown-jewel boundary; locks to Postgres; no DNS tokens on targets; CF token scoping; session/workstation threat rows; YubiOTP dropped; KEK to KMS; git-URL deploy source; app-log viewer, env lifecycle, DB provisioning, webhook deploys, rollback history, adopt-existing-site added; Finding model + IA + alert policy; build process in `build-process.md`. Same-day: Partner Deploy API & MCP (§K). Hardening scripts delivered (`harden-ubuntu.sh`, `update-cloudflare-ufw.sh`, `verify-hardening.sh`, `hub-upgrade.sh`). **UPDATE 2026-08-02:** `server-watch.sh` also delivered (per-server ntfy tokens per review3 §M3/§V8), joining the script set under review3 §Q8 custody.

## 12.7 Third addendum layer (2026-08-02)
Two documents added 2026-08-02: **`plan-addendum-2026-08-02-scanner-node-ts.md`** (modular scanner; node-ts module) and **`plan-addendum-2026-08-02-review3.md`** (Review Round 3 — the topmost authoritative patch layer). Precedence: **review3 > scanner addendum > 07-30 addendum > this document.**

---

## 13. Suggested first action
Start Phase 0 + the Scanner (Phase 1) — immediate value (honest readiness audit of existing projects), zero infrastructure risk, and every later phase consumes its output.
