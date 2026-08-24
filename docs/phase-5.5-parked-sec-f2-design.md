# Phase 5.5 parked Security F2 — git-push is a wake-up

Not a new phase. Next honest §I line after SRE/UX parked minors
(`8fac33b`): MUST-panel Security F2 (Minor). Not U1, not Phase 6,
not UX F1 picker, not Architect F1 `core → deploys`.

**Branch:** `p55-sec-f2` cut from master `8fac33b`.
**Spec authority:** `docs/phase-5.5-design-note.md` r2 §7 C6 / D-085;
MUST-panel Security F2
(`.superpowers/sdd/phase-5.5-tasks/phase-5.5-must-security.md`).

## Lands this wave

Unsigned `{type: "git-push"}` outbox items stay a **second message on the
same Hub poller**. The plant remains an untrusted hint (`git_url` through
`validate_git_url`). **The planted `sha` is not the branch head.**

`enqueue_git_push` must:

1. `validate_git_url(git_url, resolve=False)` on the planted URL before any
   Site match (keep). Blocked URLs still audit `git-url-blocked` and do not
   enqueue.
2. Consult `git_ls_remote` (T1: monkeypatched / injected) **only** for a
   `Project` whose `git_url` and `git_ref` equal the planted url/ref.
   Other git-sourced sites get `""` and are not woken.
3. Pass that lookup into existing `poll()` so confirm / windowed / same-sha
   / AUTO still belong to the poller. The lookup **returns the git-host
   sha**, never the planted `sha`.
4. Keep processing git-push when `PARTNER_API_ENABLED` is False (operator
   git is not the partner kill-switch).

Do not add a public GitHub/Gitea/webhook route. Do not add an intake
secret. Do not treat planted SHA as `ls_remote`. Do not fleet-poll every
`Project.git_url` on one hint.

## Does not land

- U1 / `named-partner.md` stub / invented `HUB_TEST_*` tokens.
- HMAC enablement / MCP / live intake / live `git ls-remote` against the
  internet in T1 (tests inject `git_ls_remote`).
- UX F1 destination picker; Architect F1 `core → deploys`; `0013` reopen.
- Changing `BATCH_CAP` or a second outbox fetch.

## Exit

One green `make review-round` + `conformance --phase 5 --exclude-tier t2
--exclude-tier t3` on the merged tree. Five-seat MERGE (or
MERGE-AFTER-FIXES + scoped re-review). Panel vote is the merge click.
