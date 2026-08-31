# Known issues

## 2026-08-29 — Vite development hostname mismatch

- **Observed:** Opening Deploy Hub at `http://127.0.0.1:5173/` and using a
  passkey showed Chrome's `This is an invalid domain.`
- **Cause:** WebAuthn refuses IP origins. `127.0.0.1` is not a valid RP ID;
  `localhost` is. The Hub's RP ID is `localhost` in dev.
- **Fix:** The UI now says to open `http://localhost` instead of surfacing
  Chrome's string. `?sim=` screens skip the live ceremony. Passkey login and
  enrollment on a real session still require `http://localhost`, not
  `127.0.0.1`.
- **Status:** Closed 2026-08-31.

