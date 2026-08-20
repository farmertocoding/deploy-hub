# Project Inventory (§J7) — required before Phase 1 exit

**Status: 6 of 6 done** (TAKKO 2026-08-03; E-invoice, hr-saas-starter, SATURDAYS_site
2026-08-04; ecommerce + fb-group-poster 2026-08-20). Review3 §V12: **no third
framework lurks**. The four deploy-shaped repos are Django(+React SPA). The two
that were waiting on connected folders are not a third framework either:
`ecommerce` is a leftover Python venv with no application source; `fb-group-poster`
is Django 4.2 WSGI (startproject) + sqlite. Joseph 2026-08-09: both **not deploy
candidates**, so those two rows are §V12 clause (a) only (framework, serving
process, scanner module). The django + node-ts + fallback module list holds. The
Phase 2 deploy-target pool is unchanged: TAKKO, SATURDAYS_site, hr-saas-starter.

## Cross-cutting findings (from the four deploy-shaped projects; the 2026-08-20 pair added no third framework and no new fleet pattern)

1. **uv-managed Django is the fleet norm** (TAKKO, E-invoice, hr-saas-starter): the
   django module must read `pyproject.toml` + `uv.lock`, not assume requirements.txt.
   Version tolerance up to **Python 3.14 / Django 6** (E-invoice).
2. **ASGI-only serving everywhere** (daphne ×3, uvicorn ×1; Channels/WS load-bearing
   in 3 of 4): the master plan's "gunicorn 2×CPU+1" default is wrong for this fleet —
   the module must detect and preserve the ASGI server command. The 2026-08-20 pair
   does not reopen this: ecommerce has no server, and fb-group-poster is classic
   WSGI but is not a deploy candidate.
3. **Every project ships its own compose stack with sidecar processes**: celery
   worker+beat (E-invoice, hr-saas), APScheduler runner as a supervised second process
   with heartbeat-file healthcheck (SATURDAYS), scheduler loop service (TAKKO), and
   **migrate-as-one-shot-compose-service** (E-invoice, hr-saas). The django module
   needs an "extra processes" concept in the manifest (aligns with §V5's component
   list + §E8/§N7 jobs machinery), and the adopt path must be **compose-aware**, not
   single-container.
4. **Site-owned edge containers collide with the Hub's host Caddy** (Caddy ×3,
   nginx ×1, some with baked-in SPA + ACME ownership): the recurring adopt decision —
   keep site edge behind Tunnel vs strip it and fold into host Caddy — needs to be a
   named wizard question. Same-origin (cookies/CSRF/WS) is a hard constraint in ALL
   four; any adopt topology that splits SPA/API origins breaks them.
5. **Fail-loud prod settings are the norm** (`os.environ[...]` hard-fails, `${VAR:?}`
   compose guards) — the scanner's settings checks will mostly pass; what it must
   verify instead is that the *hub* supplies the required env or containers exit at boot.
6. **Apps own some ops duties the Hub also wants** (hr-saas: nightly age-encrypted
   pg_dump→S3 inside Celery beat; E-invoice: backup.sh): the Hub should *verify* these
   ran rather than blindly double-implementing — a per-site "backup ownership" flag in
   the §N6 registry.
7. **Frontends are build artifacts, never Node services** (Vite → static, Node
   22/24 build-only): the node-ts module applies to none of these; `static` module +
   build step covers them (validates §V4 precedence design).

---

## TAKKO — たっこ市集 (Takko Market) · inventoried 2026-08-03

**Shape:** Django 5.2 backend + separate React SPA. Matches the **django scanner
module** (frontend is a static Vite build served by Caddy — no node runtime in prod).

| Facet | Finding | Deploy-system relevance |
|---|---|---|
| Python / Django | 3.13 · Django >=5.2,<6 · managed with **uv** (uv.lock present) | Scanner must handle uv projects, not just pip/requirements (Phase 1 fixture note) |
| Settings | `config.settings.{dev,prod}` split, env-driven via **django-environ** (`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `CORS/CSRF origins`, `SITE_BASE_URL`) | Passes the §5.1 settings-split check already |
| ASGI/WS | Channels 4.2 + channels-redis, daphne; WS routes `/ws/me/`, `/ws/admin/`, `/ws/ping/` (panel-only, push-only) | T3 ws smoke test (review3 §Q7) applies; runserver won't serve — target must run daphne |
| DB | Postgres 17 (dev on host port **5442** — port offsets, machine runs other projects) | Fresh-host guard §E6 is live: his machines are occupied; adopt-path, not fresh provision |
| Jobs | Celery installed but **no worker/beat** — a `scheduler` compose service loops two idempotent management commands every 300 s | Wizard's scheduled-jobs manifest (§E8) replaces this loop cleanly |
| Media | Local Docker volume `media:/app/media`, served by its own Caddy | **Not scale-ready** (§9.5.6) — fine; single-instance site. Object storage is the later fix |
| Edge | Own prod compose ships a **Caddy container** (SPA + API/WS proxy + media, LE via SITE_ADDRESS) | Overlaps the Hub's host-level Caddy. Adopt decision needed: keep site-owned Caddy behind Tunnel (spike), or fold routing into host Caddy (Hub-managed). Spike can use the compose stack as-is |
| Dockerfiles | `backend.Dockerfile`, `web.Dockerfile` present | §E7: existing Dockerfile = input the module validates, never a bypass |
| Frontend | React 19, Vite 8, TS 6, Tailwind 4, TanStack Query, react-router 7; **oxlint**; vitest + Playwright | Build check = `tsc -b && vite build` |
| Auth model | Session cookies (not JWT), CSRF header — same choice as the Hub | — |
| Tests | pytest + pytest-asyncio, concurrency tests required by its CLAUDE.md for seats/stock | Good readiness-report demo material |

**Spike fit:** strong candidate for Phase 0.5 — real users' shape (WS, media, SPA),
already containerized, and its compose-prod stack can sit behind a Cloudflare Tunnel
with only a `SITE_ADDRESS` change and port mapping. The one caution: its home
machine already serves things on offset ports — the tunnel avoids all port conflicts
(outbound-only), which is exactly the §6.5 argument.
*(Post-spike note 2026-08-03: this adopt path was proven live — takko-spike.takko.market
via Tunnel; see phase-0.5-spike-record.md.)*

**Open questions for the adopt path:** where does TAKKO currently run in prod (which
machine/network zone)? Email sending (marketplace/emails.py) — which SMTP provider,
and is the credential env-driven?

---

## E-invoice · inventoried 2026-08-04

**Shape:** `django` module (app/backend, uv-managed Django 6 on Python 3.14, ASGI/Daphne) — but the project ships its own complete **docker-compose production stack** (2 Dockerfiles, 6 services), so the honest adopt-path is the `dockerfile`/compose route with the django scanner used for introspection only. The Vite SPA is not a standalone `static` deploy: it is baked into an nginx image that also proxies `/api` + `/ws` (same-origin is load-bearing). No third framework anywhere.

| Facet | Finding | Deploy-system relevance |
|---|---|---|
| Language/framework | Python **3.14** (`requires-python = ">=3.14"`), **Django >=6.0.7** + DRF 3.17, Channels 4.3 (`channels[daphne]`), Celery 5.6, psycopg3 — `app/backend/pyproject.toml` + `uv.lock` (uv-managed, no requirements.txt). Frontend: React 19.2 + Vite 8 + TS ~6.0, TanStack Query 5, react-router 8 (`app/frontend/package.json`) | django scanner must read **pyproject.toml + uv.lock** and tolerate Py 3.14/Django 6. Frontend build is npm (`npm ci` + `tsc -b && vite build`), Node 24 in the image — a build artifact, not a service |
| Settings/config | Split settings `config/settings/{base,dev,prod}.py`; fully env-driven; **prod.py uses `os.environ[...]` hard-fails** for `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `FIELD_ENCRYPTION_KEYS` and refuses to boot on the repo's public dev Fernet key | Deploy must supply real secrets or containers exit at boot. `FIELD_ENCRYPTION_KEYS` is a rotatable list — crown-jewel secret, never alongside DB backups |
| Serving | **ASGI only**: Daphne serves HTTP + WebSocket in one process (port 8000 in-container; dev runserver on **8800**) | Never split HTTP/WS; gunicorn alone breaks the app. Health endpoint `/api/health/` (needs Host in ALLOWED_HOSTS + `X-Forwarded-Proto: https`) |
| DB | PostgreSQL 17; prod adds `CONN_MAX_AGE`, health checks, `DB_SSLMODE` | Migrations run as a **one-shot `migrate` compose service** all others depend on |
| Jobs | Celery worker (invoice transmission to VAC, webhook delivery) + **Celery beat** (30-min compliance sweep). Redis broker. `ACKS_LATE=False` deliberately | Two extra long-running processes, same image. **Beat down = no compliance alerts ever** — monitor it. Beat schedule needs writable volume |
| Media/static | No MEDIA_ROOT; reports generated synchronously per-request (nginx 120s read timeout on `/api/`). Static image-baked (WhiteNoise + nginx immutable SPA assets) | No persistent media volume; no runtime collectstatic |
| Edge/Dockerfiles | Complete: `backend.Dockerfile` (python:3.14-slim + uv, non-root, `AUTOBAHN_USE_NVX=0`), `frontend.Dockerfile` (node:24 → nginx:1.29), compose-prod (postgres/redis/migrate/backend/worker/beat/web), backup/restore scripts, runbook | Adopt as-is: only `web` publishes a port (default 8080). Expects external TLS terminator setting `X-Forwarded-Proto: https` — Caddy/Cloudflare slot in front |
| Frontend | SPA **same-origin required** (relative `/api/v1`, csrftoken cookie; prod CORS empty by design). `tsc -b` mandatory. `design_handoff_invoice_console/` + `einvoice-project/` are non-deployable reference artifacts | Do not serve SPA from a separate origin. Scanner should classify sibling dirs as references |
| Auth model | Session+CSRF for humans, hashed per-company **API keys** (`ic_…` bearer) for tenant ERPs with Idempotency-Key, Redis-backed DRF throttles protecting government 字軌 ranges | Redis loss degrades throttling + channel layer + broker at once |
| Tests | 46 backend test files (pytest, MIG golden byte-equivalence, allocator concurrency), vitest + typecheck, Playwright e2e; CI runs all **plus `django check --deploy` and e2e against production images** | CI already build-validates the prod images — hub can reuse as gate |

**Adopt-path notes:** Not currently deployed anywhere (Amego live-VAC adapter fixture-tested only). Self-hosts via compose-prod with a single host port (`WEB_PORT`=8080); adopt flow = TLS terminator in front (sets `X-Forwarded-Proto`), supply `.env.prod` secrets, run documented `createsuperuser` **with a TTY**. Monitoring must cover 4 app processes (web/worker/**beat**/+pg/redis); platform console exposes last-sweep age. First scanner mismatch to expect: **uv/pyproject on Python 3.14/Django 6**.

**Open questions:** coexist-or-share Postgres/Redis with other sites on the same host? Does the django module handle uv-lock + ASGI-only, or does this land on the dockerfile/compose fallback by design? When does Amego sandbox validation happen (gates real-tenant go-live)?

---

## hr-saas-starter · inventoried 2026-08-04

**Shape:** `django` module (backend) + `static` module (Vite SPA build) — but the prod topology is a self-contained compose stack (Caddy edge + uvicorn ASGI + Celery worker/beat + one-shot migrate service); treat `docker-compose.prod.yml` as the deploy unit or teach the django module about worker/beat/migrate sidecars.

| Facet | Finding | Deploy-system relevance |
|---|---|---|
| Language/framework | Python ≥3.12, Django ≥5.2,<6 + DRF ≥3.16, **uv-managed** (`backend/pyproject.toml`, `uv.lock`); Celery[redis] ≥5.4; WeasyPrint (Cairo/Pango system libs), pyrage, boto3, line-bot-sdk. Frontend: React 19, TS 5.8, Vite 6 | uv again; image needs apt libs (pango/cairo, fonts-noto-cjk) — plain-buildpack Django won't run |
| Settings/config | Split `config/settings/{base,dev,test,e2e,prod}.py`; raw `os.environ` fail-loud in prod (SECRET_KEY, ALLOWED_HOSTS, REDIS_URL, FIELD_ENCRYPTION_KEYS/HMAC); compose `${VAR:?}` guards; canonical env list `deploy/prod.env.example` (expects `/etc/hoyun/prod.env`, 0600) | Env-driven and self-documenting; PDPA Fernet keys — losing them loses data |
| Serving | ASGI: prod runs **uvicorn** `config.asgi --proxy-headers` :8000; plain Django ASGI, **no Channels yet** (M2 later — no deployment change when it lands) | Module must support uvicorn ASGI command |
| DB | PostgreSQL 16, Postgres-only semantics (daterange, ExclusionConstraint); dev publishes **54320**; prod db has **no ports** (deliberate — Docker bypasses ufw). Migrate as one-shot service with `service_completed_successfully` deps | Port-offset pattern again; migrate-as-service pattern again |
| Jobs | Celery worker + beat; beat schedule includes **nightly 03:00 pg_dump → age-encrypt → S3 backup** (`core/backup.py`, MinIO restore drill via `make restore-drill`) | The app owns its DB backup — hub should VERIFY it ran, not double-implement (§N6 backup-ownership flag) |
| Media/static | `MEDIA_ROOT` local dir (診斷證明 PII uploads), **`MEDIA_URL = None`** — bytes served only via audited API route; STATIC_ROOT admin-only, no whitenoise | Media volume = stateful PII: persist + back up, never expose via edge |
| Edge/Dockerfiles | `backend/Dockerfile` (python:3.12-slim, uv 0.9.5, no CMD). **No frontend image**: Caddy 2 (`deploy/Caddyfile`) terminates TLS/ACME, proxies API, serves SPA from bind-mounted `./frontend/dist`, strict CSP/HSTS. CI deploy jobs are **E5 placeholders** (`HOYUN_IMAGE` ghcr tag doesn't exist) | Deploy hub would own image build+push AND the frontend dist build+sync. Caddy collision question again. `/healthz` exists (DB-free liveness) |
| Frontend | Vite 6 + React 19 + react-router 8 + TanStack Query 5 + Sentry; `npm run build` = `tsc --noEmit && vite build`; dev proxy `/api → :8000` | Standard `static` module fit, Node 22 |
| Auth model | Custom User, **JWT (simplejwt)**: 15-min access + 7-day rotating refresh in HttpOnly SameSite=Strict cookie path-scoped to `/api/v1/auth/`; TOTP MFA for Owner/HR-Admin; Argon2; per-request tenant middleware; Redis-backed throttles (fail-loud) | First JWT project in the fleet (cookie-scoped, not localStorage — defensible); Redis availability-critical |
| Tests | 93 backend test files (~1,900 tests), pytest + hypothesis + schemathesis; coverage gate 90 (+100% branch on payroll engine); hard gate markers (golden/leaktest/filing/lawfirst); vitest ~186 + Playwright; committed OpenAPI snapshot + `make schema-diff`; **`make prod-config`** validates prod compose; `tests/test_deployment.py` cross-checks compose ↔ env example | Rich pre-deploy gates the hub can call: `make gates`, `make prod-config`, **`make freeze-check`** (statutory-deadline deploy freeze — pipeline must honor exit 1) |

**Adopt-path notes:** Not yet deployed (CI deploy = E5 placeholders; no registry/host/DNS). Prod design: single-VM compose, caddy on 80/443(+HTTP/3), db/redis unpublished. Dev ports 54320/63790 chosen to avoid collisions with other projects on the same machine. `reference_impl/hoyun_hr/` is **dead reference code** — exclude from scanning. Multi-tenancy is application-level (shared DB, leaktest gate, no RLS) — one stack serves all tenants; `make leaktest` belongs in any pre-deploy pipeline.

**Open questions:** who builds `frontend/dist` for prod (no image/artifact hand-off exists)? Does the hub provide the registry `HOYUN_IMAGE` assumes, or build on-host? Adopt Caddy-in-stack on a dedicated VM vs strip-and-front (CSP/same-origin must survive either way)? Should the pipeline call `make freeze-check`? Sentry/LINE `disabled` placeholder convention vs hub secret templating?

---

## SATURDAYS_site · inventoried 2026-08-04

**Shape:** `django` (backend) + `static` (Vite SPA build) — but the *actual* deploy is a 5-service docker-compose stack (multi-target `Dockerfile`: `backend` + `caddy`), so the adopt path is closer to `dockerfile`/compose. A plain `django` scan would MISS the mandatory second process (auction scheduler) and the ASGI/WebSocket requirement.

| Facet | Finding | Deploy-system relevance |
|---|---|---|
| Language/framework | Python 3.12, Django 5.2.16 + DRF 3.17.1 + Channels 4.3.2 + daphne 4.2.2, APScheduler 3.11.3, Stripe 15.3.0, whitenoise, polib (`backend/requirements.txt` — pip this time) | ASGI (daphne) mandatory — live-bidding WS `/ws/*` load-bearing |
| Settings/config | Single `settings.py`, everything via **python-decouple** from `.env`; `DEBUG` is the sole prod switch (flips HSTS, secure cookies, proxy header, whitenoise manifest) | Third settings pattern in the fleet (decouple, single-file); daphne needs `--proxy-headers` or IP throttles break |
| Serving | Caddy container: TLS/ACME, SPA from `/srv/dist` (baked into caddy image), `/media` volume, proxies `/api /ws /django-admin /static /sitemap.xml /robots.txt` → daphne :8000. Single-origin, zero CORS | Edge-ownership decision again; SPA-fallback + WS upgrade + media serving must survive any fronting |
| DB | PostgreSQL 16 pinned (dev on **5433**); **Postgres mandatory** (`select_for_update()` bidding concurrency) | Port-offset pattern again |
| Jobs | `manage.py run_auction_scheduler` — **required separate long-running process** (APScheduler: close lots every 5 s), own compose service with **heartbeat-file healthcheck** (`/tmp/scheduler-heartbeat`, stale >60 s = wedged) | NOT a cron — a supervised second process. Heartbeat file = ready-made monitor probe |
| Media/static | `MEDIA_ROOT=/app/media` named volume served by Caddy; whitenoise manifest static, collectstatic at image build (build fails on broken refs) | Media volume persistence + backup (currently manual tar — a gap the hub should own) |
| Edge/Dockerfiles | One root `Dockerfile`, 3 stages/2 targets: frontend (node:24, `npm ci` + vite build) → backend (non-root, entrypoint) → caddy (+built SPA). Entrypoint runs `migrate` + `seed_roles` only for the `daphne` arg; scheduler waits on web healthcheck (migration-race solved in-image) | Compose adoptable nearly as-is |
| Frontend | React 19.2 + react-router 7.18 + Vite 8.1, oxlint, origin-relative API/WS (no build-time env), pre-compiled committed `.mo` i18n | node-ts does NOT apply (Node build-only) |
| Auth model | Django session cookies (custom SafeSessionMiddleware), email-verified registration, staff RBAC via Groups/capabilities + `seed_roles`, social login scaffolded (env-gated), invoice `public_token` bearer | Same-origin hard constraint again |
| Tests | 49 test modules (Django runner, needs real Postgres); `QA_CHECKLIST.md` = 93-item bilingual manual QA (last run 2026-07-31: 88 pass); Playwright as scripts only; **no CI config in repo** | CI gate = `manage.py test` vs Postgres service; DEPLOY.md's §Verifying steps are a ready post-deploy probe checklist |

**Adopt-path notes:** Current method per DEPLOY.md: git clone + `.env` on a single VPS, `docker compose up -d --build`; routine deploy = pull/build/up; rollback = checkout previous `deploy-YYYY-MM-DD` tag and rebuild. Domain **saturdays-succulents.com** (root `.env` in the copy is still `DOMAIN=localhost` — possibly not live yet). Health surface already exists (compose healthchecks: `/robots.txt`, scheduler heartbeat, pg_isready, redis ping).

**Open questions:** actually live anywhere today, and on which VPS? Hub takes over Caddy/TLS vs fronts it? Does the django module model (a) ASGI/daphne, (b) a required non-web sibling process, (c) Redis as hard runtime dep — or does this ride the compose fallback? Backups (pg_dump cron, media tar) in scope for the monitor? `seed_photos` hotlinks Squarespace CDN — flag before go-live.

---

## ecommerce · inventoried 2026-08-20 · not a deploy candidate (Joseph, 2026-08-09)

**Shape check only (§V12 clause a).** The connected folder named `ecommerce` is
not an application. It is a Python 3.10.6 virtualenv (`pyvenv.cfg` dated 2023-07-01)
with Django **4.2.2** installed into `lib/python3.10/site-packages`. Layout is
`bin/ include/ lib/ pyvenv.cfg`. No `manage.py`, no `pyproject.toml`, no
`requirements.txt`, no compose, no Dockerfile, no HTML tree.

| Facet | Finding |
|---|---|
| Framework | none — leftover venv, not a project |
| Serving process | none |
| Scanner module | **none**. Live `scanner.core.detect_modules` / `scan` on the folder: empty module list, 0 checks. Installed Django in `site-packages` is not treated as a project (pinned by `test_j7_a_venv_with_django_installed_is_not_a_django_project`). |

**Adopt-path notes:** N/A. Not a third framework. Same Django version as
fb-group-poster (4.2.2); most likely the venv that used to serve that app, with
the source later living in the `fb-group-poster` folder.

---

## fb-group-poster · inventoried 2026-08-20 · not a deploy candidate (Joseph, 2026-08-09)

**Shape check only (§V12 clause a).** Local Django 4.2.2 `startproject` app
(`fbposter` + `posts`) for drafting Facebook group posts: session UI, product
scrape via stdlib urllib, sqlite, local `media/`. No compose, no Dockerfile, no
lockfile, no `requirements.txt`.

| Facet | Finding |
|---|---|
| Framework | **Django 4.2.2** (startproject banner in `fbposter/settings.py`). Single `settings.py`, `DEBUG = True`, sqlite3, local `MEDIA_ROOT`. Frontend is Django templates, not a Node SPA. |
| Serving process | **WSGI**. `WSGI_APPLICATION = 'fbposter.wsgi.application'`. `asgi.py` is the unused startproject default (`get_asgi_application()`, no `ProtocolTypeRouter`, no Channels). No daphne/uvicorn. Intended runtime is `manage.py runserver` on the laptop. |
| Scanner module | **`django`**. Live scan 2026-08-20: `modules=['django']`, service command `gunicorn fbposter.wsgi:application --bind 0.0.0.0:8000`, `django.server-mode` ok/WSGI. Blockers that are honest for this tree: `core.secret-scan`, `django.debug-hardcoded`, `django.secret-key-literal`, `django.dependency-manifest`. Pinned by `test_j7_startproject_asgi_py_without_channels_stays_wsgi` (startproject `asgi.py` without Channels must not flip the command to daphne). |

**Adopt-path notes:** N/A — Joseph ruled it out of the deploy-candidate pool.
Useful only as a WSGI counterexample: the fleet-norm "ASGI-only serving
everywhere" still holds for the three Phase 2 targets; this sixth named folder
is classic WSGI and is not going through the pipeline. No third framework.
