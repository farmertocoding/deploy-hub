# Phase 7.0 Design Note — Restore into a clean container (T1)

**Phase:** 7.0 per addendum §I Phase 7 (restore UI) and D-063 reverse
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r1 — restore UI only. Binding §7.
**Estimate:** hours-to-a-day. Protective cut: **D-122**. Phase 6.12 T1 MUST is on `master` @ `4d2ec21`. Router Advisor, preview environments, LAN ghosts, Pulumi/managed-DB/LB, Azure, HMAC, U1, live AWS, ScalePolicy, auto, AMI, cooldown auto, real drain, 30s health-pull are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. Reuse `CheckRun.Kind.RESTORE_CLEAN`. No new BackupUnit columns. Never return ciphertext or the backup key.
**Panel:** §7 is binding. Expert team continue (Joseph delegated commit/merge/push).

## 1. What lands this wave

Phase 4 shipped persist + Beat + P1 + Sites list + T2 test-now + a §6.6 restore **command block**. D-063 parked the Restore POST / button as Phase 7. The monthly drill already unseals off-live into a tempfile (`monitor/drills.py::_restore_to_clean_container`). This wave adds the T1 operator path that calls that same primitive for a chosen dump. It does **not** overwrite a live volume. It does **not** return ciphertext.

### 1.1 MUST

1. **T1 restore, clean-container only.** `provision/backup.py::restore_to_clean(unit, *, checkrun_pk, restore_to_clean=None)` unseals that dump with `Secret.Kind.BACKUP_KEY` (never the KEK) and calls `restore_to_clean or _restore_to_clean_container`. Writes `CheckRun.Kind.RESTORE_CLEAN` metadata only (`schema_version`, `unit_id`, `site_id`, `checkrun_pk`). Failure audits `backup-restore-failed` and does not write plaintext into CheckRun/AuditEvent/Finding.

2. **HTTP.** `POST /api/v1/sites/{site_id}/backups/{unit_id}/restore/` `BackupRestoreView`: `RequireRecentTouch`; serializer `{checkrun_pk: int, confirm_name: str}` with `confirm_name == site.name`. ACTION_TIERS `{id: "site.backup_restore", tier: "T1", label: "Restore into clean container"}`. `T1_HTTP["site.backup_restore"]` = that path (`{pk}` = site_id; view also needs `unit_id` — use `/api/v1/sites/{pk}/backups/1/restore/` in T1_HTTP and resolve). `make generate-client`. 201 `{ok: true, unit_id, checkrun_pk}`. 4xx on missing dump / wrong confirm / seam refuse. Tests inject `restore_to_clean=` via wrapping the view's callee; never live docker.

3. **Command block stays.** List payload still includes `restore_command`. Sites `BackupPanel` still renders `<pre>`. Add the T1 ActionButton; no color-only status. Rewrite Phase 4 `test_no_restore_route_exists` / `test_restore_is_command_block_not_a_post` so they still pin the command block and now pin the T1 route (RequireRecentTouch). Do not delete the command block.

4. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST ids phase 7, tier-less. Add `conformance-7` (`--phase 7 --exclude-tier t2 --exclude-tier t3`); it is **not** a `review-round` or `nightly-gates` prereq. Do not waive U1. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO`. Do not claim `provision/backup.py` wholesale if already claimed; claim the restore view module if new.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| T1 Restore into clean container; BACKUP_KEY; no ciphertext in API | **MUST** |
| Command block remains | **MUST** |
| Never overwrite live volume / never KEK | **MUST** |
| Router Advisor / preview envs / LAN ghosts | **OUT** |
| Pulumi / managed-DB / LB / Azure | **OUT** |
| Overwrite-live restore | **OUT** |
| U1 / HMAC / live AWS | Unchanged park |

## 2. Interfaces that change

**Python:** `provision/backup.py::restore_to_clean` (+ optional `checkrun_pk` on unseal). `provision/views.py::BackupRestoreView`. `provision/urls.py`. `core/actions.py` ACTION_TIERS. `tests/test_webauthn_t1.py` T1_HTTP. `tests/test_backup_operator.py` rewrite Phase 4 no-route pins. Frontend `Sites.jsx` BackupPanel + frontend test. Acceptance `tests/acceptance/test_phase_7.py`. Demo `conformance/demos/phase-7.md`.

**Not changed:** drill body `_restore_to_clean_container` (reuse). Beat `backup-nightly` / `restore-clean` drill schedule. Evaluator / overflow. Findings.jsx / Chrome.jsx / seed overflow rows. No schema.

## 3. Applicable registry reqs

Task 0 — new MUST ids, phase 7, no `tier:`. `source: phase-7-design-note.md §3`. Compute `text_hash:` via `--print-text-hashes`. Add `PHASE_7_MUST_IDS` + `allowed_sources`.

- `BACKUP-RESTORE-CLEAN-T1` — `phase: 7`, `verify: test`. `text:` T1 POST site.backup_restore Restore into clean container unseals a chosen BackupUnit dump with BACKUP_KEY never the KEK, writes RESTORE_CLEAN metadata only, never returns ciphertext, never overwrites a live volume; OPEN confirm is type-the-site-name; tests inject restore_to_clean.
- `BACKUP-RESTORE-COMMAND-REMAINS` — `phase: 7`, `verify: test`. `text:` Sites backup list still returns restore_command and BackupPanel still renders the pre command block after the T1 restore button lands.
- `P7-RESTORE-DEMO` — `phase: 7`, `verify: demo`, `demo: conformance/demos/phase-7.md`.

## 4. Exit demo

A site with a sealed dump, T1 touch + type-the-name, injected restore_to_clean → 201 ok; RESTORE_CLEAN CheckRun metadata has unit_id and checkrun_pk; response has no dump bytes; live SiteInstance untouched; command block still on GET list. Wrong confirm → 4xx. Record: `conformance/demos/phase-7.md`. Honest: no live docker overwrite, no KEK, no Azure, no U1.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-122** Protective cut — T1 restore-to-clean only. Reuses drill tempfile primitive. Command block stays. Router Advisor / preview / LAN / Azure / overwrite-live are later.
- **D-123** ACTION_TIERS `site.backup_restore` T1. Confirm is type-the-site-name. Inject `restore_to_clean`. Never bind key/ciphertext from the request.
- **D-124** Everyday gates stay phase 5 minus live. New ids phase 7 tier-less. `conformance-7` is the phase gate and is not a review-round prereq. U1 stays uncovered.

## 6. Protective cut (D-122)

MUST = T1 clean-container restore + command block remains + registry + conformance-7. Router / preview / LAN / Pulumi / Azure / overwrite-live / U1 are **OUT**.

## 7. Closed contract (binding)

**C1 Unseal.** BACKUP_KEY + existing AAD. Missing dump / missing key → 4xx, no CheckRun SUCCEEDED, no ciphertext in the 4xx body.

**C2 Clean only.** Default restore writes a tempfile and deletes it (existing `_restore_to_clean_container`). Injected `restore_to_clean(unit, plaintext)` in tests records `len(plaintext)` and must not be called with sealed bytes. Never `docker` in T1 mutating_calls.

**C3 HTTP.** Label exactly `Restore into clean container`. Serializer `{checkrun_pk, confirm_name}` only. generate-client.

**C4 Command block.** GET list still has `restore_command` containing `age -d` / `pg_restore` and "BACKUP_KEY". JSX still has `<pre` and `restore_command`.

**C5 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Do not mark Phase 4 leftover tests with the new ids except the rewritten pins. Do not mark `P6-SCALER-DEMO`. Do not mark `P7-RESTORE-DEMO` on pytest.

**C6 Registry.** Task 0 adds the three ids, `PHASE_7_MUST_IDS`, `conformance-7`, Makefile `.PHONY`. Do not rewrite Phase 4/6 `text:`.

**C7 Copy.** No `\binstance\b` in new operator copy except existing tokens. NAV six. File map may edit `Sites.jsx` BackupPanel only (not Findings.jsx / Chrome.jsx).

**C8 Gate.** `python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3` verifies the new ids; U1 uncovered-only allowed.

## 8. Follow-up only (not this wave)

Router Advisor (tunnel: verify nothing forwarded). Preview environments (private repos). LAN discovery ghosts. Restore-overwrite-live. Azure. Pulumi.
