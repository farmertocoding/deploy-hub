# Live Site adoption API

**Phase:** recommended-next-sequence Wave 2
**Date:** 2026-08-26
**Binding:** `docs/recommended-next-sequence-execution.md` §7. Closed CheckRun schema is S2: `{schema_version, site_id, temp_name, stage, started_at}` only.

## HTTP

`POST /api/v1/sites/{site_id}/adopt/`

Start body (unknown fields refused):

```json
{ "live_compose_path": "/explicit/operator/path/docker-compose.yml" }
```

`live_compose_path` is optional. Blank/absent skips the drift check. The server does not search `/srv/sites` or guess a path.

Cancel body:

```json
{ "cancel": true }
```

`cancel` together with `live_compose_path` is 400.

Responses:

| Code | When |
|---|---|
| 202 | Newly queued start or cancel. Body is the operation resource. |
| 200 | Idempotent repeat: requested outcome already holds; no new work queued. |
| 400 | Malformed body, unknown fields, overlong path, conflicting fields. |
| 401/403 | Unauthenticated / unauthorized. |
| 404 | Unknown Site. |
| 409 | Lifecycle conflict (cancel at/after flip; missing primary_target). |
| 503 | Required DNS/transport seam unconfigured; retry after configuration. |

Operation resource (no secrets): `{checkrun_id, site_id, stage, status, queued, temp_name}`.

## Persisted stage

Canonical `CheckRun.results.stage` values: `temp_dns`, `verify`, `flip`, `decommission`, `cleanup`. Empty string only before the worker writes the first stage.

UI presentation: `abandoned` is not stored. Cancel before flip runs `cleanup`; the UI maps `cleanup` after a pre-flip cancel the same as a completed cleanup. Start after a terminal `cleanup` may queue a **new** CheckRun (at most one **active** adopt per Site). Duplicate start while `status=running` returns the existing run.

## Transitions

| Current | Start | Cancel |
|---|---|---|
| No run | Queue adopt (202) | 200 no-op |
| temp_dns / verify, running | 200 existing | Queue cleanup (202) |
| flip / decommission, running | 200 existing | 409; use rollback |
| cleanup (terminal) | Queue new adopt (202) | 200 completed |
| failed before flip | Retry reuses `temp_name` (202) | Queue cleanup if temp may exist |

## Execution

HTTP never runs SSH, Docker, DNS, or probes. Celery `run_adopt(site_id, checkrun_id, live_compose_path)` and `cancel_adopt(site_id, checkrun_id)` carry IDs and the optional path scalar only. The worker reloads Site/CheckRun, assembles `desired` with `dns_provider_for` / `resolve_production_seams` and `SshTransport(primary_target)`, then calls `adopt_flow` or `cleanup`. `deploys/` does not import `providers.cloudflare`.
