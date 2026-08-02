# Phase 0 exit demo record (P0-WS-DEMO)

Status: **not yet performed** — this file is the template; the recorded walkthrough
replaces this text at phase exit (a placeholder here does NOT satisfy the gate:
the Adversarial verifier checks the content, not the file's existence).

Checklist to record:

- [ ] `docker compose up` from clean checkout
- [ ] create superuser, log in (password), enroll TOTP, re-login with TOTP
- [ ] open demo panel, launch job from validated form (see an error + a warning first)
- [ ] log lines stream live over ws/events with monotonic seq
- [ ] kill socket in devtools → reconnect → snapshot-then-stream, no gap, no dupes
- [ ] date, commit sha, screen recording path
