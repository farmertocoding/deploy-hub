# DECISIONS.md — decide and log, don't ask (build-process.md §6)

| id | date | decision | why | what would reverse it |
|---|---|---|---|---|
| D-001 | 2026-08-02 | Repo lives in `~/Documents/deploy-hub` (local folder), per Joseph. GitHub private repo required no later than Phase 2.5. | CI (GitHub Actions) is load-bearing from Phase 2.5; local is fine while the skeleton stabilizes. | Nothing — pushing to GitHub is additive. |
| D-002 | 2026-08-02 | TS client generation tool deferred until the frontend consumes the schema (Phase 0 build, not scaffold). Candidates: openapi-typescript + zod via openapi-zod-client. | §4.5 requires generated-not-hand-written mirroring; tool choice is swappable behind the generated-artifacts dir. | Either tool failing to express DRF warning contract. |
| D-003 | 2026-08-02 | Scaffold ships single-call login (password+TOTP in one POST) rather than a two-step ceremony. | Mockup-first; the session model is identical, so splitting later is a UI change only. | UX review finding in a Phase 0 round. |
