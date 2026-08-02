# Deploy Hub

Self-hosted deployment control plane — Phase 0 skeleton.

**Plan docs live in the Claude project** ("web deploy automation & monitor"):
`deploy-system-plan.md` (master) · `plan-addendum-2026-07-30.md` · scanner addendum ·
`plan-addendum-2026-08-02-review3.md` (topmost patch layer) · `build-process.md`.
The Phase 0 design note is in `docs/phase-0-design-note.md`.

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

TOTP enrollment (until the UI flow lands): add a TOTP device for your user in
`/admin` → *TOTP devices* → scan the QR with your authenticator. Login then
requires password + code — mandatory-2FA per plan §6.10.

## Gates

```bash
make test          # T1 unit + acceptance
make lint          # ruff, bandit, pip-audit, log-scrubber grep
make conformance   # conformance/check.py --phase 0 (review3 §Q2)
make review-round  # all mechanical gates
```

## Layout (§D4 — the import rule is a test)

`hub/` settings+celery+asgi · `core/` AuditEvent, Transport seam, auth ·
`vault/ catalog/ scanner/ provision/ deploys/ reconcile/ monitor/ scaling/` empty
shells — features land phase by phase · `providers/` interfaces + fakes (the ONLY
home for boto3/azure/cloudflare imports) · `realtime/` the multiplexed socket
contract + demo job · `conformance/` requirements registry + check ·
`simulation/` seed fixtures (§F8).

Sensitive paths (human-merge only) are listed in `conformance/paths.yaml`.
