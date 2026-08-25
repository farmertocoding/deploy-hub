# Phase 6.10 tasks — Scale-in overflow + ephemeral reaper (T1 Fake)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** T1 `scale_in_overflow` unjoins the overflow origin then terminates via FakeCloudProvider; `reap_stale_ephemerals` flags 24h leftovers and does not terminate.

**Spec:** `docs/phase-6.10-design-note.md` **r2**. §7 is binding.

**Branch:** work in place. Do not push.

## Global Constraints

- Do not invent `HUB_TEST_*` / HMAC tokens. Do not stub `named-partner.md`.
- `0014` closed. No `Target.created_at`. Attack does not block scale-in. Partner refuses.
- Everyday gates stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. U1 uncovered.
- Do not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`. Do not fold the 6.8 leftover.
- TDD, long why HEREDOC, no amend.

Protective cut (**D-113**): MUST = Tasks 0–2.

### Task 0: Registry + custody (D-113…D-115)

`PHASE_6_MUST_IDS` += both ids; `allowed_sources` += `phase-6.10-design-note.md §3`. Copy D-113…D-115. Add both reqs `phase: 6` `verify: test` no `tier:`; `text_hash` via `--print-text-hashes`. Claim `monitor/overflow_reaper.py` in paths.yaml **and** CODEOWNERS. Append P2 `ephemeral-overflow-orphan` in `monitor/alert_rules.py`.

### Task 1: scale_in + reaper + T1 HTTP

C1–C7, C10. Tests in `tests/test_overflow_scale_in.py` as C8. generate-client.

### Task 2: Acceptance + demo

NAMED `test_overflow_scale_in_unjoins_terminates_and_reaper_flags` calls the two source tests. Append demo. Honesty: no live AWS, no drain window, no Beat, no 30s health-pull.
