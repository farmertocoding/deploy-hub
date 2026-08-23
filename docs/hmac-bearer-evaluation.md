# HMAC/bearer enablement — evaluation (D-083 / §K2 / D-075)

**Date:** 2026-08-24 · **Decision:** do **not** default-on; do **not** enable this phase.
**Seat:** Phase 5.5 Task 10 SLIP writeup. Spec: design note D-083 / D-075 / D-085 / addendum §K2 / §K9 / C4.

§K2's **now** step already shipped: per-partner Ed25519, Hub re-verify against Partner pubkey slots, 5-minute window, Postgres nonce cache (10 min TTL), Stripe-style Idempotency-Key 24 h, shared `conformance/fixtures/partner-signature-vectors.json` (Phase 5.5 MUST, `PART-Q9-SHARED-VECTORS` / `PART-K2-REPLAY-AT-HUB`, D-083). The Phase 5.5 research item was HMAC/bearer as a compatibility fallback for partners who cannot sign. That is a different control. This writeup is the evaluation. It is **not** D-083 reverse — reverse is a named partner who cannot sign Ed25519 **plus** a ruling that HMAC enablement is MUST.

## What HMAC/bearer would actually be (inbound shared secret, not Standard Webhooks)

§K2 offered HMAC/bearer **only** as a compatibility fallback. Secret + verify would be **Hub-side only** (C4). Intake stays credential-free: public keys + counters + outbox. The remaining designs:

- **HMAC over the C4 canonical string.** Same `{method}\n{path}\n{hex(sha256(body))}\n{timestamp}\n{nonce}`. Partner and Hub share a secret. Verify needs that secret. Dual-secret rotate (current + previous) so a leak is recoverable without lockout, same shape as later Standard Webhooks dual-secret slots. Instant Hub revoke stays (drop the vault row / `suspended=True`).
- **Bearer.** An `Authorization` token with no MAC. Authenticates the caller, not the request. Replay is the token unless timestamp+nonce+HMAC are rebuilt on top — at which point it is HMAC, not bearer.

Neither is Standard Webhooks. `whsec_` is Hub-**egress** HMAC-SHA256 over `id.timestamp.payload` (`Secret.Kind.WEBHOOK_SECRET`, C7, already MUST). Reusing `whsec_` / `WEBHOOK_SECRET` for inbound partner auth would mix egress signing with inbound auth and put a Hub-egress secret on the partner's request path.

`Secret.Kind` has no HMAC inbound kind (`test_secret_kind_has_no_hmac`). `Partner` stores `pubkey_current` / `pubkey_previous` only. `intake/verify.py` and `core/partner_verify.py` consume Ed25519 vectors and `X-Partner-*` headers. Pinned env is `INTAKE_URL` / `PARTNER_API_ENABLED` / `PARTNER_FLEET_MAX_SITES`. There is no `HUB_INTAKE_HMAC`.

## Why this wave does not enable it

1. **No named partner who cannot sign.** §K9 parked Ed25519-vs-HMAC on real partner capability. C1: do not build until a named partner cannot sign. U1's committed partner does not exist; inventing one (or an HMAC path for a hypothetical) is enablement. T1 fixture slugs are not this proof.

2. **A Hub-held inbound secret is impersonation.** Compromising the Hub today yields Partner *public* keys and vaulted `whsec_` (egress). The attacker cannot mint inbound partner requests; the Ed25519 private key was shown once and is not vaulted. An HMAC secret in the Hub vault is worse: the attacker mints **new** partner-shaped jobs for that partner until the secret is rotated. Bearer is the same hole without body binding. CircleCI 2023 extracted secrets from a running process — Hub-side HMAC sits in that same process.

3. **Hub-side-only HMAC fights the credential-free intake.** K1 models a fully-compromised intake as survivable because it holds public keys, not secrets. HMAC at the edge requires the secret on intake — K1 dies. HMAC only at the Hub means intake cannot cheap-reject: it either holds the secret, or it forwards unverified HMAC-shaped jobs into the outbox (flood; a compromised intake plants jobs that only fail at Hub re-verify). Ed25519 is the control that lets the edge reject with material the intake is allowed to hold. Deferred-auth HMAC is a different architecture, not a flag.

4. **The MUST control already landed.** Dual pubkey slots, Hub re-verify, 5-minute window, nonce TTL 10 min, idempotency 24 h, quota-exceeded Hub refuse, replay rejected even when Fake intake forwards (D-083 / PART-K2 / PART-Q9). Instant Hub revocation is MUST. 90-day rotate playbook may slip; that slip is not HMAC. HMAC is the later compatibility item; this fleet still has no named partner who cannot sign.

5. **Enablement is a verifier rewrite, not a setting.** New vault Kind, Hub HMAC verify path, HMAC cases in the shared vector file, dual-secret rotate, possibly an intake branch. Changing `intake/verify.py` or `core/partner_verify.py` here is enablement. Inventing `HUB_INTAKE_HMAC` / `HUB_TEST_PARTNER_TOKEN` / `HUB_WEBHOOK_SECRET` is forbidden. Registering a phase-5.5 due id this writeup would have to mark would put HMAC on the MUST line (D-075 reverse).

## Ed25519 stays (D-083 is not reversed)

This writeup does not replace `intake/verify.py` or `core/partner_verify.py`. Dual pubkey slots, Hub re-verify, nonce cache, idempotency, shared vectors remain. D-083 reverse ("a named partner who cannot sign Ed25519 plus a ruling that HMAC enablement is MUST") is unmet. D-075 reverse (taking a slip item onto the MUST line) is unmet. D-085: HMAC is evaluation-only until a named partner cannot sign.

## What would change the decision

Joseph naming a committed partner (U1) **who cannot sign Ed25519** **and** a ruling that HMAC enablement is MUST **and** secret + verify remain Hub-side only (intake stays credential-free; no HMAC kind on intake; no `HUB_INTAKE_HMAC`) **and** Ed25519 stays the default for every partner who can sign. Until then the Hub does not generate an inbound HMAC secret, does not vault one, does not add a `Secret.Kind` for HMAC, and does not accept HMAC or bearer on either verifier.

## Explicitly not done

No HMAC secret in the vault. No `Secret.Kind` for inbound HMAC. No change to `intake/verify.py` or `core/partner_verify.py`. No HMAC/bearer header path. No `HUB_INTAKE_HMAC` / `HUB_TEST_PARTNER_TOKEN` / `HUB_WEBHOOK_SECRET`. No phase-5.5 due id (this writeup is not one; `P55-PARTNER-DEMO` must not claim enablement). Ed25519 stays. MUST demo does not wait.
