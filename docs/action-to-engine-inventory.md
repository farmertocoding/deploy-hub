# Action-to-engine inventory

Wave 1 of `docs/recommended-next-sequence-execution.md`. Live readiness as of 2026-08-26.

| Action ID | Resource | Tier | UI | HTTP | Engine | Live readiness |
|---|---|---|---|---|---|---|
| site.rollback | Site | T3 | Sites.jsx SiteStatus | POST /api/v1/sites/{id}/rollback/ | deploys.pipeline.rollback | Live |
| site.restart | Site | T3 | Sites.jsx SiteStatus | none | none | Unavailable: not implemented |
| check.rerun | CheckRun (Site detail) | T3 | Sites.jsx SiteStatus | none | none | Unavailable: not implemented |
| site.preview_create | Site | T2 | Sites.jsx SiteStatus | POST /api/v1/sites/{id}/preview/ | git_visibility_for → create_preview | Live when preview_ready; else unavailable: not configured. Client visibility is 400. |
| site.adopt.start | Site | T2 | AdoptPlan | POST /api/v1/sites/{id}/adopt/ | adopt_service + adopt_flow | Live (Wave 2) |
| site.adopt.cancel | Site | T2 | AdoptPlan | POST /api/v1/sites/{id}/adopt/ `{cancel:true}` | adopt_service + cleanup | Live (Wave 2); 409 after flip |
| site.backup_restore | Site | T1 | BackupPanel | POST .../backups/{unit}/restore/ | provision restore | Live (T1 confirm) |
| target.router_probe | Target | T3 | Targets.jsx Router tab | POST /api/v1/targets/{id}/router-probe/ | wan_probe_for(target) → probe_nothing_forwarded | Live when collect_payload.wan_probe_adapter is allowlisted; else unavailable. Body cannot enable the seam. |
| target.delete | Target | T1 | Targets | POST .../targets/{id}/delete/ | provision | Live |

Error copy uses four kinds: `not implemented`, `not configured`, `refused`, `failed`.
