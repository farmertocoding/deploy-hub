# Phase 0 exit demo — recorded (P0-WS-DEMO)

**Date:** 2026-08-03 · **Commit under test:** `fc708fa` (round-1 fixes included; the
walkthrough now also exercises the CSRF-protected login via the /me bootstrap and the
server-side 2FA gate) · **Recorded by:** Cowork session — automated Playwright
walkthrough, driver checked in at `scripts_dev/ws_reconnect_demo.py`, re-runnable.

## Environment

Native run of the compose stack's services (cloud dev container, no docker daemon):
Redis 7 with `requirepass` — the **real `channels_redis` layer and real Redis seq
counters**, not the in-memory fallback — daphne on :8000, Celery worker on the
`deploys` queue, vite dev server on :5173 proxying `/api` + `/ws`, SQLite (dev DB
fallback). `docker compose up` itself was not executed here (no docker daemon in
this environment); the compose file only changes *where* these same services run.
**Residual for the Mac: one compose-stack bring-up spot-check.**

## Template checklist → result

- [x] ~~docker compose up from clean checkout~~ → services run natively, same code
      paths (see Environment); compose bring-up = one spot-check on the Mac
- [x] create user, log in (password), enroll TOTP **via the UI**, re-login with TOTP
- [x] open demo panel, launch from validated form — **error first, then warning**
- [x] log lines stream live over `/ws/events/` with monotonic seq
- [x] kill socket → reconnect → snapshot-then-stream, **no gap, no dupes** (asserted
      programmatically by the driver, not by eye)
- [x] date, commit sha, evidence: transcript below + `phase-0/*.png`

## Transcript (driver output, verbatim)

```
[20:06:57] open http://127.0.0.1:5173 — fresh user 'demo-operator', no TOTP device
[20:06:58] logged in with password; UI forces TOTP enrollment (§6.10 mandatory-2FA)
[20:06:59] TOTP enrolled via UI; 8 recovery codes shown once
[20:07:00] re-login without TOTP rejected (second factor enforced)
[20:07:00] waiting 30s for the next TOTP window (replay protection)
[20:07:31] re-logged in with password + TOTP; demo panel open; socket live
[20:07:32] form error blocks client-side via generated zod mirror (§4.5)
[20:07:32] server warning (slow_demo) rendered with 409 + confirm flow
[20:07:33] streaming: 2 lines rendered, killing socket now
[20:07:33] socket killed: status=reconnecting; worker keeps publishing meanwhile
[20:07:35] socket reconnected (1.5s backoff): snapshot refetched, stream resumed
[20:07:40] recovered panel shows all 9 lines exactly once — no gap, no duplicates
[20:07:40] PASS: full Phase 0 exit walkthrough
```

Screenshots (in `phase-0/`): `01-login` · `02-enroll-qr` (otpauth + QR) ·
`03-recovery-codes` (shown once) · `04-form-error` (zod mirror blocks client-side) ·
`05-form-warning` (409 + confirm) · `06-streaming` · `07-dead` (*reconnecting*,
worker still publishing) · `08-recovered` (all 9 lines exactly once).

## Post-recording re-verification

The driver was re-run against later round HEADs and passed **4/4 consecutive runs**
at `573d17b` (post round-4 accept-then-close). An earlier intermittent failure during
these reruns was traced to stale Celery worker processes running pre-rewrite code in
the recording environment — an environment artifact, not a product defect — but it
still yielded one real client fix (syncTopic catch scope, commit `573d17b`).

## Notes

- The 24 s pause is django-otp's replay protection working as designed: the code
  burned at enrollment-confirm is rejected for re-login inside the same 30 s window.
  Incidental live proof of the §6.10 chain, worth keeping in the recording.
- The socket kill is a forced `close()` on the live WebSocket (devtools-equivalent).
  Chromium's `Network.emulateNetworkConditions` does **not** sever an established
  ws — noted for future drivers.

## Findings fixed during the recording (each with its regression test)

1. **Snapshot was hardcoded `data: []`** — lines published while a socket was dead
   were unrecoverable; "no gap" was unachievable as coded. Fix: `publish(...,
   history=True)` capped per-topic history (500) + snapshot returns it; the panel
   repaints from `__snapshot`. Tests: `tests/test_snapshot_history.py`.
2. **CSRF cookie never planted in a clean browser** — the SPA is vite-served, so no
   Django GET ran `get_token()`; login worked but every later authed POST 403'd.
   Invisible to the pytest client (CSRF skipped); found only because this demo runs
   a real browser. Fix: `LoginView` plants the cookie (sensitive-path diff,
   `core/views.py`) + dev-only `CSRF_TRUSTED_ORIGINS` for the vite origins (its
   proxy rewrites Host) + the UI now surfaces non-contract statuses (403/500)
   instead of silently ignoring them.
   Tests: `tests/test_issue_p0_csrf_cookie_missing.py` (uses
   `enforce_csrf_checks=True` — the gap the plain client can't see).
