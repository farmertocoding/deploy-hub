# Phase 5.5 parked Architect F1 — core ↛ deploys

Not a new phase. Next honest §I line after UX F1 (`46bef7a`):
MUST-panel Architect F1 (Minor). Not U1, not Phase 6, not UX F1 picker,
not Security F2 git-push, not parked F3–F5.

**Branch:** `p55-arch-f1` cut from master `46bef7a`.
**Spec:** `docs/phase-5.5-design-note.md` r2 D4/D5 + `core/models.py` L5;
MUST Architect F1 (parked: lazy `deploys.models` from
`core/partner_jobs.py` / `core/partner_verify.py`).

## Lands

Chosen D4 cut: **(b) a core-defined `PartnerDeployStore`, implemented in
`deploys/`, wired from `deploys.apps.DeploysConfig.ready()`.** Same arrow
as `core.events` / `realtime.apps.ready()`. Core never imports `deploys`
(function-level still counts). A thin helper in `deploys/` that
`core/partner_jobs.py` imports **is the cycle**, not a cut.

1. `tests/test_import_rule.py` grows `"deploys" not in _direct_imports("core")`
   (kernel docstring is **core imports nothing from deploys/**, not
   “nothing core imports may import deploys”). `_reaches("core", "deploys")
   is None` stays red on the **legal** `core → monitor → deploys` M2 path
   after the direct edge leaves; do not special-case `_reaches` or delete
   `monitor → deploys`. Detector pin: `"deploys" in _direct_imports("wizard")`
   (and `_reaches("wizard", "deploys")` is not None as a walk pin only).
2. `core/partner_deploys.py` is the D5 port (`PartnerDeployStore` +
   `register_store` / `_require`). Unwired calls fail loud (`RuntimeError`
   matching `not wired`). No fallback `import deploys`. Peer of
   `core/events.py` — do not claim it on `paths.yaml`; isolation stays in
   already-claimed `core/partner_jobs.py`. `DeploysConfig.ready()` is the
   wiring path (events analog: unwind `_store`, assert fail-loud, call
   `get_app_config("deploys").ready()`, live `DjangoPartnerDeployStore`).
   Do not register from `tests/conftest.py`. Do not skip `ready()` when
   `DEBUG`. INSTALLED_APPS stays `"deploys"`.
3. `deploys/partner_ledger.py` is the Django ORM adapter (lookups,
   queued Manifest+Deployment insert, U2 `count_since`). Ordinary; do
   not broaden `deploys/**` on the sensitive-path list.
4. `core/partner_jobs.py` stays the r2 materialize home. Isolation
   refuses, PartnerSite mint, template pin, and `_ship` stay there.
   `get_partner_deployment` / `_existing_deployment` / `_create` go
   through the store. `monitor/intake_poll.py` still calls
   `core.partner_jobs.materialize`.
5. `evaluate_quotas` counts U2 deploys (`deploys_per_day`, 3/min,
   100/day per site) through the same store. Filter shape stays:
   partner-wide via `manifest__site__partner_site__partner`; per-site
   via `manifest__site` + `manifest__created_at`.
6. Isolation is still Partner + PartnerSite + `destination_order`. No
   `Site.tier` / `Site.partner_id` / `Target.tier`.

## Why not (a) or (c)

**(a)** Moving `partner_jobs` into `deploys/` is a recorded r2 deviation
(Task 0 claimed `core/partner_jobs.py` as materialize home) and puts
Hub-host / co-host / destination-order / V3 refuse in the pipeline
package. Isolation models live in `core`. Do not.

**(c)** PartnerSite-side counters need a Hub column → `0014`. D-076
default is no new Hub wave; a port counts the same Deployment rows
without schema. Counters also leave Manifest/Deployment **writes and
IDOR lookups** in core, so they cannot break the cycle alone. Do not
reopen `0013`. Do not add `0014`.

## Does not land

U1 / `named-partner.md` stub / invented `HUB_TEST_*` tokens. HMAC
enablement. MCP. Phase 6. UX F1 picker. Security F2 git-push. Parked
F3–F5. `0013`/`0014`. `core/models.py` edits. New registry ids.
`Site.tier` / `Site.partner_id` / `Target.tier`. Fake ledger that
ignores planted Manifest/Deployment rows. Collapsing the intake wall.

## Exit

One green `make review-round` + `conformance --phase 5 --exclude-tier t2
--exclude-tier t3` on the merged tree. Five-seat MERGE (or
MERGE-AFTER-FIXES + scoped re-review). Panel vote is the merge click.
The tooth is `test_core_stays_free_of_deploys` green because
`"deploys" not in _direct_imports("core")` after the edge moved, not
because `_reaches` was broken.
