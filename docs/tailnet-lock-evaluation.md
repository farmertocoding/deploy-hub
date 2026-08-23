# Tailnet-lock enablement — evaluation (D-058 / §J5)

**Date:** 2026-08-23 · **Decision:** do **not** default-on; do **not** enable this phase.
**Seat:** Phase 4 Task 11 SLIP writeup. Spec: design note D-058 / §1.1 item 8 / addendum §B8 / §J4.

The MUST line this phase is the Tailscale **device-list poll** (Task 9): skip-unless-configured, FakeTailscale, P2 `tailscale-unknown-device`. Tailnet-lock **enablement** is a different control. Session↔device binding is the same shape (§J5) and is also not default-on.

## Current UX (docs last validated 2025-12-02; GA 2025-06)

Tailnet Lock is off by default. Enablement is an Owner/Admin CLI ceremony, not a Hub setting:

1. Nodes on v1.46.1+.
2. Admin console → Enable Tailnet Lock → pick **at least two** signing nodes → copy `tailscale lock init …`.
3. Run that command on a signing node. It prints **ten disablement secrets once**. Lose them (and the optional Tailscale-support copy) and the tailnet is not recoverable except by `lock local-disable` on every node.
4. Every **new** node is Locked out until a signing node runs `tailscale lock sign nodekey:…` (or a client signing URL on macOS/Windows/iOS). Linux targets — the Hub fleet — are CLI-sign only.
5. Pre-signed auth keys exist, but they are a new credential class with their own custody. Android cannot sign.

That is the "signing ceremony on the 2-minute enrollment flow" §B8 asked Phase 4 to look at. It is still a ceremony. Webhooks for pending-signature landed with GA; they do not remove the need for a trusted TLK holder.

## Why this wave does not enable it

1. **Enrollment is unattended today.** Provisioner catalog + short-lived pre-auth keys join a target in one playbook. Lock-on would leave every new box Locked out until a signing node is reachable and someone runs `lock sign`. The Hub must not grow a Tailscale signing sidecar to paper over that — that is enablement.
2. **Disablement secrets are a new crown jewel.** Ten long passwords, shown once, offline storage required. A solo operator who loses them cannot disable lock; a compromised coordination server that *has* a support-copy can. That trade is real, and it is not a default we flip from the Hub.
3. **The MUST control already watches the failure mode.** A device the Hub did not create files P2 `tailscale-unknown-device`. SSO 2FA on the tailnet-owning account is the adopted §B8 account hardening. Lock is the stronger "do not trust the coordination server" control; this fleet has not taken that threat onto the MUST line.
4. **TOFU at init.** The first `lock init` still trusts the control plane for the initial TKA state. Nodes should then compare `tailscale lock status`. The Hub has no place to store or compare that set without new tables (Task 11 cannot open a schema wave).

## Session↔device binding (§J5)

Same ruling: not default-on. Binding Django/Channels sessions to a Tailscale device identity needs custom middleware, a stable device id on the request, and a story for the phone passkey on a network that is not the tailnet. Idle timeout + WebAuthn T1 touch are the MUST stolen-session controls this phase. Re-open §J5 only with a spike that proves the bind without inventing a device table.

## What would change the decision

Joseph ruling that a coordination-server insert is in-scope for this tailnet **and** a named signing-node runbook that does not block `provision` **and** disablement secrets in the same offline box as the KEK break-glass copy. Until then the Hub does not run `tailscale lock init`, does not store disablement secrets, and does not require `lock sign` on enroll.

## Explicitly not done

No `tailscale lock` in catalog or provisioner. No Hub setting that flips lock. No disablement secret in the vault. Device poll stays skip-unless-configured (`HUB_TAILSCALE_API_TOKEN_REF` default empty). Do not invent a live Tailscale token env.
