# Phase 3 leftovers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Phase 3 leftover line the standing goal still names: parked panel findings that are product defects, an honest REL-P2 30-min form, the T2 write_runbook EACCES that keeps `conformance-3` red, and (environment permitting) a real T2 fixture image. Do not claim LE-staging or a 24 h Hub-down.

**Architecture:** Phase 3 MUST is already on `master` (`c4357ae`). This plan is a leftover wave on `p3-left`, cut from that commit. Each task is a small honesty fix with its own tests. No new schema. No adopt / Settings-bind / Origin-CA plant (those stay Phase 3b). No `WAIVERS.md` line for T2/T3 `failed`/`error`.

**Tech Stack:** Django, pytest, Celery Beat, Transport argv lists, Cloudflare `observe_token`.

**Spec:** `docs/phase-3-design-note.md` r2; panel reports under `.superpowers/sdd/phase-3-tasks/phase-3-panel-{architect,security,qe}.md`; `DECISIONS.md` D-015 / D-025 / D-042 / D-046; `WAIVERS.md` leftover lines.

## Global Constraints

Copy from `.superpowers/sdd/phase-3-tasks/global-constraints.md` (verbatim Phase 3 constraints). Additional leftovers rules:

- Do not waive `failed` / `error` / `not-collected` in `conformance/check.py`.
- Do not invent `HUB_TEST_CF_TOKEN`. LE-staging stays skipped-only + dated waiver until the token exists.
- Do not claim a 24 h Hub-down. D-042 retirement is a dated 24 h record, not this wave.
- Do not start Task 15 adopt or Settings-bind + Origin-CA plant.
- One schema wave is closed (`0009_phase3.py`). No new migration this wave.
- Sensitive paths (`providers/`, `deploys/`, `vault/`) still wait for a leftover panel vote before `master`.
- TDD: failing test first, then the code. Report RED then GREEN.
- Commit style: long "why" HEREDOC; no amend; no `--no-verify`.

---

## Preflight (controller)

| Pair / task | Shared surface | Finding | Ruling |
|---|---|---|---|
| 1 vs 3 | none | — | — |
| 2 vs 4 | none | — | — |
| 2 vs registry | `observe_token` return shape | Task 2 may add `total_count`; registry still judges `len(zones)` unless the brief says otherwise | Ruling: Task 2 makes `observe_token` refuse / surface `total_count`; `_verify_scope` and the daily audit must use the same set-size fact. Cost if wrong: wall and audit drift. |
| 5 vs T9 tests | `tests/test_drills.py` SUCCEEDED on default no-op | QE I1 | Ruling: default no-op cannot SUCCEEDED. The marked default-prober test must change. Cost if wrong: siteless nightly still SKIPPED (unchanged). |
| 7 vs D-025 | PIPE-S4 alpine waiver | Environmental | Ruling: do not retire the waiver without a green real-image T2 run. |
| 8 LE-staging | `HUB_TEST_CF_TOKEN` unset on this host | Blocked | Ruling: do not dispatch. Self-refusing probe stays. |

---

## Task 1 — write_runbook second write must not EACCES

**Title:** A root-owned 0400 BREAK-GLASS.md cannot be refreshed by `chmod u+w` + SFTP put.

**Why:** Task 16 parked this. `chmod u+w` unlocks the *owner* (root), not the deploy user. T2 run-twice then `put()`s as deploy and gets `EACCES`. That is a `conformance-3` `failed` row, not a waiver.

**Files:** `deploys/breakglass.py`, `tests/test_breakglass.py`.

**Do:**
- Follow `deploys/certs.py::_atomic_write`'s install shape: `put` to `{path}.tmp` (deploy-writable), `sudo mv` onto the final path, `sudo chown root:root`, `sudo chmod 0400`.
- Do **not** `chmod u+w` the existing 0400 file as the unlock.
- Argv lists only. No heredoc. No interpolated shell.
- Put mode of the temp file is 0o400.
- First write (missing file) and second write (existing 0400 root) both succeed.

**Tests (TDD):**
- `test_second_write_over_root_0400_uses_temp_then_sudo_mv` — plant a root-owned 0400 file in a transport that raises `PermissionError` / `EACCES` on `put` to a root-owned path; assert `write_runbook` still replaces contents; assert calls include `put` to `*.tmp` and `sudo mv`.
- Existing SEC-P5 / VAL-45 tests stay green (no secrets, impact first, argv lists). Update path assertions if they assumed `put` lands on the final path.

**Not this task:** changing runbook body, TLS writes, catalog caddy-log-roll.

**Exact req ids:** SEC-P5-BREAK-GLASS (existing markers stay; do not add a new full-text id).

---

## Task 2 — Zone-set authorization is set size, not page length

**Title:** D-046 must read `result_info.total_count`, not `len(result)`.

**Why:** Security panel Minor 3. `observe_token` returns `len(result)` and ignores `total_count` / `total_pages`. A later `per_page=1` would construct an over-scoped token.

**Files:** `providers/cloudflare.py`, `providers/registry.py`, `monitor/token_audit.py` (only if it re-derives set size), `tests/test_dns_zone_wall.py`, `tests/test_cloudflare_adapter.py`, `tests/test_cf_token_audit.py` as needed.

**Do:**
- After the zone probe, read `result_info.total_count` when present. Refuse (do not return a one-row page as "one zone") when `total_count` is present and `!= 1`.
- When `total_count` is absent, keep today's `len(result)==1` rule (and document that in the helper docstring).
- `_verify_scope` and the daily audit must refuse on the same fact.
- Do not change `ZONE_PROBE_PATH` (`/zones?per_page=50`).
- Do not add `@pytest.mark.req` on `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`.

**Tests (TDD):**
- Probe body with one row and `result_info.total_count=2` (or `total_pages=2`) is refused at construction and files the audit Finding.
- Probe body with one row and `total_count=1` still constructs.
- Absent `result_info` + `len==1` still constructs (compat).

---

## Task 3 — Rollback HTTP is 403 unauthenticated and 409 on seam refuse

**Title:** A live T3 mutation must pin unauth refusal; `DeploySeamRefused` is 409, not 500.

**Why:** Security Minor 4 + Architect Minor 6 / QE Minor 5.

**Files:** `deploys/views.py`, `tests/test_site_rollback_http.py`.

**Do:**
- Catch `DeploySeamRefused` from `rollback()` and return HTTP 409 with a `detail` that does **not** include vault values or token bytes. The factory still files the Finding and marks the row `failed`.
- Add `test_rollback_requires_session` (403, no session) matching connect's shape. Optional CSRF pin with `enforce_csrf_checks=True` if the existing client harness makes that cheap; session 403 is the MUST.
- Do not invent a second rollback engine. `rollback(pk)` kwargs stay empty.

**Tests (TDD):**
- Unauthenticated POST → 403, no Deployment created.
- `rollback` raising `DeploySeamRefused` → 409, Finding still exists if the factory filed it (monkeypatch can raise after the factory's documented side effects, or raise a bare `DeploySeamRefused` and assert 409).

---

## Task 4 — Weekly rollup sends; digest SMTP failure files a Finding

**Title:** `digest-weekly` is a named owner that must deliver; a swallow with no Finding is not fail-visible.

**Why:** Architect Minor 4 / QE Minors 2 and 8.

**Files:** `monitor/digest.py`, `tests/test_delivery_behaviors.py` (or a focused digest test module if that file is the current owner).

**Do:**
- `build_weekly_rollup` renders the inbox set and calls `_send` the same way `build_digest` does (subject names the week).
- `_send` on exception files a P2 Finding through `core.findings.finding()` (fingerprint stable, e.g. `digest:smtp-failed`) and still returns False (must not raise; push path stays unblocked).
- Finding title/body contain no mailbox contents that are secrets. Recipient address may appear; vault tokens must not.
- Do not change Beat keys or crontab.

**Tests (TDD):**
- Weekly rollup calls `mail.send_mail` (locmem).
- Forced SMTP exception files the Finding and does not raise.

---

## Task 5 — Hub-down default no-op cannot SUCCEEDED

**Title:** SUCCEEDED means the site answered *while Hub-side workers were down*. A no-op stop is not that.

**Why:** QE Important 1. Goal leftover: REL-P2 30-min path honesty. 24 h stays waived.

**Files:** `monitor/drills.py`, `tests/test_drills.py`.

**Do:**
- Keep default `stop_hub` / `start_hub` as no-ops. Do **not** invent a worker-stop that shuts Celery/Django from inside Beat.
- If the stopper used is the default no-op (identity: `stop_hub is None` or is the module default), a live-site run must **not** write `SUCCEEDED`. Write `FAILED` (or `SKIPPED`) with `results.reason` containing `hub-not-stopped`, plus a P2 Finding (`drill-missed:hub_down:hub-not-stopped` or the existing drill-missed family).
- Siteless SKIPPED + P2 Finding is unchanged.
- Injected `stop_hub` / `start_hub` keep today's SUCCEEDED/FAILED from the prober.
- `duration_s >= 86400` still raises. Do not retire the 24 h waiver.

**Tests (TDD):**
- Change `test_hub_down_uses_a_real_external_prober_by_default` so default no-op + 2xx is **not** SUCCEEDED and the GET still happened.
- New: injected stopper + 2xx is SUCCEEDED.
- Siteless SKIPPED test stays.

---

## Task 6 — Parked wording and fixture nits

**Title:** Three lies that are copy / fixtures, not product paths.

**Files:** `WAIVERS.md` (`HARNESS-T3-LE-STAGING` line), `docs/plan/plan-addendum-2026-07-30.md` Phase-5 V11 sentence (~line 177), `frontend/src/sim.js`.

**Do:**
- Waiver prose: drop retired `HUB_TEST_DNS_ZONE`; keep `HUB_TEST_CF_TOKEN` + `purpose=test` DnsZone. Fingerprint `HARNESS-T3-LE-STAGING` must still match `req_id`.
- Phase-5 sentence: stop assigning the Phase-5 week to adopt; adopt is Phase 3b. Do not rewrite the rest of §I.
- `sim.js` site fixtures include `cert_refusal` (`null` when unused) so simulation matches `project_row_body`.
- Frontend tests that snapshot site fixtures stay green.

**Not this task:** TIME_ZONE, DnsZone unique constraint, caddy-log-roll import, ntfy-on-target install, acceptance greps.

---

## Task 7 — Real T2 fixture image (may slip)

**Title:** Try the D-025 retirement path: host-built or registry-pulled image, not in-target `npm ci` on vfs.

**Files:** `tests/test_pipeline_sample_node_site.py`, maybe `images/` or a load helper. **Do not** edit `conformance/requirements.yaml` in this wave if you cannot retire the waiver.

**Do:**
- On this host Docker works (20.10.17). Spike: build `sample-node-site` **on the host** (overlay), load into `hub-test-target`, deploy that image.
- If the T2 test is green on the real image, retire `tests.test_pipeline_sample_node_site+PIPE-S4-READINESS-GATE+t2-instant-ready-stub` and un-skip `test_t2_real_node_image_builds_on_vfs` **or** replace it with the load-path proof.
- If vfs/load still fails, keep the alpine waiver and file a dated note in the report. Do not invent a green.

**Blocked-if:** hub-test-target cannot load the image. Then DONE_WITH_CONCERNS and leave the waiver.

---

## Task 8 — LE-staging credentialed run — **blocked**

`HUB_TEST_CF_TOKEN` is unset on this host. Do not dispatch. The T17 self-refusing probe stays. Retirement is the first credentialed run.

---

## Out of this wave (still parked)

Settings-bind + Origin-CA plant (3b). Adopt §1.12 (3b). Hub-central DNS-01 (3b). caddy-log-roll live import. Unused on-host ntfy publisher. `TIME_ZONE` UTC. DnsZone `(provider,name)` DB unique (needs a migration). Acceptance source-greps. Nightly wrapper string match. 24 h wall-clock drill.
