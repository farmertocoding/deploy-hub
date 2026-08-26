# Phase 7.4 tasks — Hub-central DNS-01 (T1 Fake)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Unproxied public sites get a Hub-issued certificate via injected DNS-01 (Fake leaf + TXT upsert). Beat renews `hub_dns01` rows. Live Let's Encrypt stays skipped. `TLS-B2-HUB-DNS01-UNPROXIED` waiver retires in Task 2.

**Spec:** `docs/phase-7.4-design-note.md` **r1**. §7 is binding.

**Branch:** work in place. Expert team may commit.

## Global Constraints

- Do not invent `HUB_TEST_*` / HMAC tokens. Do not stub `named-partner.md`.
- No new migration. `0015` stays closed.
- Everyday gates stay `--phase 5 --exclude-tier t2 --exclude-tier t3`.
- TDD, long why HEREDOC, no amend.
- Do not add a Caddy ACME DNS block. Do not put a DNS token on a target.
- Keep the `TLS-B2` waiver until Task 2.

Protective cut (**D-136**): MUST = Tasks 0–2.

### Task 0: Registry + custody + park (D-136…D-139)

`PHASE_7_MUST_IDS` += `P7-DNS01-DEMO`; `allowed_sources` += `phase-7.4-design-note.md §3`; subtract the demo id from `PHASE_7_TEST_IDS`. Copy D-136…D-139. Claim `deploys/dns01.py` in `paths.yaml` + CODEOWNERS. Pin `text_hash`. Do not create product files. Do not retire the TLS-B2 waiver. README honesty: not “Phase 0 skeleton”; `make conformance` is phase 5.

### Task 1: issue_unproxied + ensure_site_certificate + Beat

C1–C5, C7. Tests in `tests/test_dns01.py`. Wire `certs.py`. Beat `hub-dns01-renew-daily`. Invert product refusal tests that would contradict the new path; keep fail-closed missing-inject.

### Task 2: Mark TLS-B2 + retire waiver + demo

NAMED in `tests/acceptance/test_phase_7.py`. Append `conformance/demos/phase-7.md`. Rewrite `TLS-B2-HUB-DNS01-UNPROXIED` `text:` (drop “until it is built”). Retire the TLS-B2 waiver. Restore full-text `SEC-B2` markers only if the exfiltration scan still holds. Invert slip pins in phase 3/4/5 acceptance. Full T1 unsandboxed + `make conformance-7`.
