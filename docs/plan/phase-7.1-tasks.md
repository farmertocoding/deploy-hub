# Phase 7.1 tasks — Router Advisor (one probe)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Tunnel-mode targets get one injected WAN-forward probe that files or resolves `router-forwarded:{pk}`; Target detail shows a Router tab and T3 Probe router.

**Spec:** `docs/phase-7.1-design-note.md` **r1**. §7 is binding.

**Branch:** work in place. Expert team may commit.

## Global Constraints

- Do not invent `HUB_TEST_*` / HMAC tokens. Do not stub `named-partner.md`.
- `0014` closed. No new CheckRun.Kind. Finding only.
- Everyday gates stay `--phase 5 --exclude-tier t2 --exclude-tier t3`.
- TDD, long why HEREDOC, no amend.
- Do not fold preview / LAN / Pulumi / Azure / UPnP automation into this wave.

Protective cut (**D-125**): MUST = Tasks 0–2.

### Task 0: Registry + custody (D-125…D-127)

`PHASE_7_MUST_IDS` += three ids; `allowed_sources` += `phase-7.1-design-note.md §3`; `PHASE_7_TEST_IDS` subtracts `P7-ROUTER-DEMO`. Copy D-125…D-127. Claim `monitor/router_advisor.py` + `monitor/router_views.py` in `paths.yaml` + CODEOWNERS. Pin `text_hash` via `--print-text-hashes`. Everyday `conformance` stays phase 5.

### Task 1: probe + HTTP + Target tabs

C1–C4, C7. Tests in `tests/test_router_advisor.py`. generate-client. Frontend `targets.test.ts`.

### Task 2: Acceptance + demo

NAMED in `tests/acceptance/test_phase_7.py` call Task 1 proofs. Append `conformance/demos/phase-7.md`. `python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3`.
