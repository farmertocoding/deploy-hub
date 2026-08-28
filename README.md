# Deploy Hub

Self-hosted deployment control plane. Phases 0–7 T1 MUST are on `master`.
Phase 7 polish on this tree: restore-into-a-clean-container, Router Advisor
(one tunnel probe), LAN discovery ghosts, private-repo preview Sites,
Hub-central DNS-01 T1 Fake for unproxied sites. Live Let's Encrypt stays
skipped.

**Plan docs** (frozen copies, review3 is the topmost patch layer):
`docs/plan/deploy-system-plan.md` · `docs/plan/plan-addendum-2026-07-30.md` ·
scanner addendum · `docs/plan/plan-addendum-2026-08-02-review3.md` ·
`docs/plan/build-process.md`.

Do not invent `HUB_TEST_*` / HMAC tokens. Do not stub
`conformance/demos/named-partner.md` — `PART-U1-NAMED-PARTNER` stays
uncovered until Joseph names a partner.

## Run (dev, zero services)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver        # SQLite + in-memory channels + eager Celery
# frontend:
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## Run (compose stack — the real shape)

```bash
cp .env.example .env   # fill the three values
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Compose boots `hub.settings.compose`: DEBUG off, FakeKEK refused, `HUB_TEST_MODE`
pinned False. First start writes a 32-byte KEK at `/etc/deploy-hub/vault.key`
in the `hub-vault` volume — back that up offline and separately from Postgres.
`hub.settings.dev` (FakeKEK) is laptop `manage.py` / pytest only. Bare
`daphne` / `celery -A hub` default to `hub.settings.prod` and refuse to boot
without `HUB_SECRET_KEY`.

Login is password + TOTP (or a WebAuthn hardware touch for T1 actions).
Add a TOTP device in `/admin` → *TOTP devices* if you are bootstrapping
a fresh database.

## Gates

```bash
make test            # T1 unit + acceptance (`not t2 and not t3`)
make lint            # ruff, bandit, pip-audit, log-scrubber grep
make conformance     # check.py --phase 5 --exclude-tier t2 --exclude-tier t3
make conformance-7   # phase 7; U1 uncovered-only is allowed
make review-round    # everyday mechanical gates (still phase 5 minus live)
```

## Layout (§D4 — the import rule is a test)

`hub/` settings+celery+asgi · `core/` models, actions, auth ·
`vault/` secrets · `catalog/` · `scanner/` django + node-ts ·
`provision/` · `deploys/` pipeline + preview · `reconcile/` ·
`monitor/` findings, map, intake poll · `scaling/` ·
`intake/` partner process (not `INSTALLED_APPS`) ·
`providers/` interfaces + fakes (the ONLY home for boto3/azure/cloudflare) ·
`realtime/` multiplexed socket · `conformance/` registry + check ·
`simulation/` seed fixtures (§F8) · `frontend/` React operator UI
(NAV is six: home, sites, targets, deploys, findings, settings).

Sensitive paths (human-merge only) are listed in `conformance/paths.yaml`.
