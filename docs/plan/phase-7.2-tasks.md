# Phase 7.2 tasks — LAN discovery ghost view

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Injected LAN hosts that are not enrolled Targets appear as `kind=ghost` nodes on the fleet map. Default `lan_scan` is refuse-closed.

**Spec:** `docs/phase-7.2-design-note.md` **r1**. §7 is binding.

**Branch:** work in place. Expert team may commit.

## Global Constraints

- Do not invent `HUB_TEST_*` / HMAC tokens. Do not stub `named-partner.md`.
- `0014` closed. Ghosts are map nodes, not Findings.
- Everyday gates stay `--phase 5 --exclude-tier t2 --exclude-tier t3`.
- TDD, long why HEREDOC, no amend.
- Do not fold preview / Pulumi / Azure / live nmap into this wave.

Protective cut (**D-128**): MUST = Tasks 0–2.

### Task 0: Registry + custody (D-128…D-130)

`PHASE_7_MUST_IDS` += three ids; `allowed_sources` += `phase-7.2-design-note.md §3`; `PHASE_7_TEST_IDS` subtracts `P7-LAN-GHOST-DEMO`. Copy D-128…D-130. Claim `monitor/lan_ghosts.py` in `paths.yaml` + CODEOWNERS. Pin `text_hash` via `--print-text-hashes`. Everyday `conformance` stays phase 5. Do not create the product module.

### Task 1: attach_lan_ghosts + map kind + Map.jsx

C1–C4, C7. Tests in `tests/test_lan_ghosts.py`. generate-client. `frontend/tests/map.test.ts` ghost pin.

### Task 2: Acceptance + demo

NAMED in `tests/acceptance/test_phase_7.py` call Task 1 proofs. Append `conformance/demos/phase-7.md`. Full T1 unsandboxed + `make conformance-7`.
