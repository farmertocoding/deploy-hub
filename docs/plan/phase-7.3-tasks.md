# Phase 7.3 tasks — Preview environments (private repos only)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** T2 Create preview refuses public/missing visibility and, when private, creates a mesh-only sibling Site. Pulumi and Azure are parked in DECISIONS.

**Spec:** `docs/phase-7.3-design-note.md` **r1**. §7 is binding.

**Branch:** work in place. Expert team may commit.

## Global Constraints

- Do not invent `HUB_TEST_*` / HMAC tokens. Do not stub `named-partner.md`.
- `0015_phase73.py` is the only new migration. Do not reopen `0014`.
- Everyday gates stay `--phase 5 --exclude-tier t2 --exclude-tier t3`.
- TDD, long why HEREDOC, no amend.
- Do not auto-deploy, add a webhook, or call live GitHub.

Protective cut (**D-131**): MUST = Tasks 0–2.

### Task 0: Registry + custody + park (D-131…D-135)

`PHASE_7_MUST_IDS` += three ids; `allowed_sources` += `phase-7.3-design-note.md §3`; subtract `P7-PREVIEW-DEMO`. Copy D-131…D-135. Claim `deploys/preview.py` + `deploys/preview_views.py`. Pin `text_hash`. Do not create product files.

### Task 1: create_preview + 0015 + T2 HTTP + Sites button

C1–C4, C7. Tests in `tests/test_preview.py`. generate-client. Frontend sites test.

### Task 2: Acceptance + demo

NAMED in `tests/acceptance/test_phase_7.py`. Append `conformance/demos/phase-7.md`. Full T1 unsandboxed + `make conformance-7`.
