# YubiKey KEK rung ② — evaluation (D-059)

**Date:** 2026-08-23 · **Decision:** do **not** default-on; do **not** enable this phase.
**Seat:** Phase 4 Task 11 SLIP writeup. Spec: design note D-059 / §1.1 item 9 / addendum §A3.

YubiKeys already serve as **WebAuthn security keys** (Phase 4 MUST, SEC-A2). That is a different job. Rung ② is wrapping vault DEKs with a YubiKey HMAC-SHA1 challenge-response at Hub process start so a stolen Hub disk does not yield the KEK.

## What rung ② would actually be

- Slot configured for HMAC-SHA1 challenge-response (Yubico: USB/Lightning HID only; not NFC).
- Optional button-press so wrap/unwrap at start requires physical touch.
- Response is 20 bytes. Hub KEK material is a 32-byte AES-256-GCM key, so an HKDF (or similar) step would sit between the dongle and `LocalKeyfileKEK`'s wrap format.
- Same as KMS on the hot path: DEKs already unwrapped stay in worker memory. A dongle only gates **restart**, not a live process (the CircleCI lesson §B6).

## Why this wave does not enable it

1. **This Hub is unattended.** Rung ② needs the key plugged in (and a touch, if we take the honest homelab reading of §A3) every time a worker or API process starts. Compose restarts, deploy-of-the-deployer, and a power blip all become a 2 a.m. USB ceremony. KmsKEK (rung ③, T1 this phase) is the unattended adapter; live AWS remains a Joseph interrupt.
2. **It does not defeat a stolen live process.** The in-process DEK cache (Task 10) is load-bearing for KMS blips. The same cache means a memory scrape after boot still sees plaintext DEKs. Rung ②'s unique claim is disk-at-rest while the box is off and the dongle is elsewhere. A homelab NUC with the YubiKey left in the port loses that claim.
3. **No backend is wired, on purpose.** `vault/kek.py::get_backend()` knows `local`, `fake`, and `kms`. There is no `yubikey` / `ykchalresp` branch. Inventing one here would be enablement. Ciphertexts stay rung-portable (D-006) so a later backend can rewrap ①→② the same way Task 10 rewraps ①→③.
4. **YubiOTP stays dropped** (addendum §A2). Rung ② is not a back door for YubiCloud.

## What would change the decision

A written ruling that the Hub of record is a physically-reachable homelab **and** the operator will touch a key at every process start **and** the dongle is not stored in the same chassis as the disk. Until then: keyfile is test/dev (does not defeat a stolen Hub disk); KmsKEK is the unattended rung, refuse-unless-configured, live AWS still Joseph.

## Explicitly not done

No `VAULT_KEK_BACKEND=yubikey`. No python-yubico / ykman dependency. No challenge-response at boot. Prod still must not default to `kms`.
