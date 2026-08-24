# Phase 5.5 parked SRE/UX minors — design note

Not a new phase. Next honest §I line after 5.5 MUST + Security F3–F5
(`4c03544`): remaining MUST-panel parked minors that are product defects
and do not wait on Joseph.

**Branch:** `p55-parked-sre-ux` cut from master `4c03544`.
**Spec authority:** `docs/phase-5.5-design-note.md` r2 §7 C6/C8/C11/C12,
MUST-panel SRE F1–F3 and UX F2–F3
(`.superpowers/sdd/phase-5.5-tasks/phase-5.5-must-{sre,ux}.md`).

## Lands this wave

1. **SRE F1 — boot-never-up P1.** A configured `INTAKE_URL` that never
   succeeds must file P1 `partner-intake-unreachable` after 5 minutes of
   configured failures, not only after a success-then-gap. Persist
   `first_failure_at` on the single `INTAKE_POLL` CheckRun when
   `last_success_at` is missing; the stamp is set once and does not move
   on later fails. Empty `INTAKE_URL` still skip-persists and never files
   P1/P2 (including at `now=t0+5min`). N=3 fetch failures at one timestamp
   file P2 `hub-outbox-poll-failing` only — not P1. P1 is
   `now - first_failure_at >= UNREACHABLE_AFTER` when `last_success_at` is
   missing (`fingerprint=` explicit). Do not implement N=3 → P1. C6’s
   “last successful probe > 5 min” clock is read as “no successful probe
   in 5 min while configured.”
2. **SRE F2 — poison jobs do not kill Beat.** `_process` must not raise
   out of `poll()`: `isinstance(job, dict)` else audit + continue;
   wrap each job so an unexpected item cannot skip `_record_success` /
   `_record_failure`. Per-job errors do **not** increment
   `consecutive_failures` (C12 is fetch death, not a bad outbox row).
   After a poison success tick, N=3 fetch failures must still file P2
   (`poll()` fetch `except` → `_record_failure`; do not `_record_failure`
   from `_process`). `FakeIntakeClient.ack` must skip non-dicts when
   filtering. Within the fetched batch, process `git-push` before skip-acked
   partner-jobs. Do not ack flag-off / quota / isolation refuses.
   Do not change `BATCH_CAP`, do not add a second fetch, do not treat
   planted SHA as `ls_remote` (Security F2 / D-085 still deferred).
   The in-batch git-first drain test is a pin (already green on HEAD).
3. **SRE F3 — rate 429 is not the spend-cap P1.** `evaluate_quotas`
   files `budget-cap-hit:partner` only for quota 403 (`reason=="quota"`).
   Rate 429 (`reason=="rate"`) still refuses with `X-RateLimit-*` and
   does not upsert that P1. No new C12 kind. D-084 fingerprint stays
   for quota-abuse.
4. **UX F2 — `as_of` is last confirmed poll.** `_intake_payload()["as_of"]`
   is `INTAKE_POLL.results["last_success_at"]`, never `timezone.now()` and
   never `first_failure_at`. Null if there has never been a success,
   including `status=error` from an open `partner-intake-unreachable`
   Finding. Error/degraded chrome uses that stamp for `data as of HH:MM:SS`
   and omits the clause when null.
5. **UX F3 — Suspended is named.** PartnersPanel shows the word
   `Suspended` (not color-only) when `PartnerPublic.suspended` is true.
   Overlay copy stays stop/detach/revoke. No 7th NAV, no picker (UX F1
   deferred).

## Does not land

- U1 / `named-partner.md` stub / invented `HUB_TEST_*` tokens.
- HMAC enablement / MCP / live intake / CF-for-SaaS.
- Security F2 (git-push SHA as `ls_remote`) — D-085 larger poller change.
- UX F1 destination-order picker.
- Architect F1 `core → deploys` cycle (do not reopen `0013`).
- New registry ids. Pin existing `PART-HUB-POLL` / `PART-U2-QUOTAS` /
  `PART-M2-GIT-WEBHOOK` / `UX-P55-PARTNERS`.
- Everyday `conformance`/`review-round` stay `--phase 5 --exclude-tier t2
  --exclude-tier t3` (D-080). No `t4`. No all-tiers 5.5.

## Exit

One green `make review-round` + `conformance --phase 5 --exclude-tier t2
--exclude-tier t3` on the merged tree. Five-seat MERGE (or MERGE-AFTER-FIXES
+ scoped re-review). Panel vote is the merge click.
