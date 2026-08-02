# REVIEW_CHECKLIST.md — v1 (Phase 0 scope)

Versioned; changes are their own reviewed PR — never modified in the round being
judged by it (build-process.md §4 anti-gaming rule). Items restating a plan
invariant carry their req id inline (review3 §Q5).

## Every round, every diff

- [ ] Every remote effect goes through `Transport` / `providers/` seams — no direct
      subprocess/SSH/SDK calls in feature code [P0-SEAMS] [P0-IMPORT-RULE]
- [ ] Every API endpoint validates through a DRF serializer; errors use
      `{field: [{code, message, hint}]}`; warnings use 409 + `confirm_warnings` [P0-VALIDATION]
- [ ] Every WebSocket subscribe passes `authorize_topic()` — no group_add anywhere else [P0-AUTHZ-TOPIC]
- [ ] Every state change a panel could show is published to its topic via `publish()` [P0-REALTIME]
- [ ] No secret in logs, Celery task args, or build contexts (pass ids, decrypt inside the task)
- [ ] Security-relevant actions call `audit()` [P0-AUDIT]
- [ ] Shell commands built as argument lists, never interpolated strings; file
      content via put(), never heredocs
- [ ] New UI state has a simulation-mode fixture (§F8)
- [ ] Feature PR carries its tests (diff-coverage gate advisory in Phase 0)
- [ ] Diff touching `conformance/paths.yaml` sensitive globs is human-merged only

## Phase 2+ additions (placeholders, activated with the features)

- [ ] Every playbook step idempotent — run-twice test records zero mutating Transport calls
- [ ] Every catalog entry has check + fix + rollback + version
- [ ] Every new table appears in retention janitor config where applicable
