# Phase 7.0 tasks — Restore into a clean container (T1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** T1 `site.backup_restore` unseals a chosen dump with BACKUP_KEY into the existing clean-container primitive; the command block remains; live volumes are never overwritten.

**Spec:** `docs/phase-7-design-note.md` **r1**. §7 is binding.

**Branch:** work in place. Expert team may commit.

## Global Constraints

- Do not invent `HUB_TEST_*` / HMAC tokens. Do not stub `named-partner.md`.
- `0014` closed. Reuse `CheckRun.Kind.RESTORE_CLEAN`. Never return ciphertext. Never the KEK.
- Everyday gates stay `--phase 5 --exclude-tier t2 --exclude-tier t3`.
- TDD, long why HEREDOC, no amend.
- Do not fold Router Advisor / preview / LAN / Azure into this wave.

Protective cut (**D-122**): MUST = Tasks 0–2.

### Task 0: Registry + conformance-7 (D-122…D-124)

`PHASE_7_MUST_IDS` += three ids; `allowed_sources` += `phase-7-design-note.md §3`. Copy D-122…D-124. Makefile `conformance-7` + `.PHONY`. Pin `text_hash` via `--print-text-hashes`. Everyday `conformance` stays phase 5.

### Task 1: restore_to_clean + T1 HTTP + BackupPanel

C1–C4, C7. Tests in `tests/test_backup_operator.py`. generate-client. Rewrite Phase 4 no-route pins.

### Task 2: Acceptance + demo

`tests/acceptance/test_phase_7.py` NAMED calls Task 1 proofs. `conformance/demos/phase-7.md`. `python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3`.
