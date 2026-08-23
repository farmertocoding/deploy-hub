# SSH-CA enablement — evaluation (D-070 / §B7 / §J2)

**Date:** 2026-08-24 · **Decision:** do **not** default-on; do **not** enable this phase.
**Seat:** Phase 5 Task 10 SLIP writeup. Spec: design note D-070 / D-064 / D-068 / addendum §B7 / §J2.

§B7's **now** step already shipped: quarterly dual-key rotate (Phase 4 MUST, `SEC-B7-SSH-QUARTERLY-ROTATE`, D-064). The Phase 5 research item was an in-Hub SSH CA issuing short-TTL certs per deploy. That is a different control. This writeup is the evaluation. It is **not** D-064 reverse — reverse is SSH-CA landing later and replacing the playbook.

## What SSH-CA would actually be (OpenSSH, not an IdP)

CISA/NSA CSI *Defending CI/CD Environments* (2023-06-28): for **human** authentication, use identity federation and phishing-resistant tokens to obtain *temporary* SSH keys; long-term private keys, when they must exist, are to be carefully managed. §J2 parked the federated-identity version because this fleet has no IdP. The remaining design is raw OpenSSH CA (5.4+; Ubuntu sshd already can):

- **User CA.** Generate an Ed25519 CA keypair. Vault the private key. Push the CA pubkey to every host as `TrustedUserCAKeys`. Per Transport, `ssh-keygen -s` a user key (`-I` identity, `-n` principals, `-V` validity). The client presents the cert. Hub `authorized_keys` lines can go away; principals / `AuthorizedPrincipalsFile` take their place. Stolen leaf certs expire; the CA key does not.
- **Host CA.** A **separate** key. Sign each sshd host key; install `HostCertificate`. Clients trust `@cert-authority` in `known_hosts`. That would replace D-068's `Target.host_key_fingerprint` pin (`PinnedHostKeyPolicy`).

A Hub-held CA private key signs both. Revocation is a KRL / `RevokedKeys` file the Hub would have to distribute — a new catalog path and a new fail-open if a host never pulls the list. The catalog drop-in (`sshd-dropin` / `99-hub-hardening.conf`) has no `TrustedUserCAKeys` / `HostCertificate`. `Secret.Kind` is `SSH_PRIVATE_KEY` only. `SshTransport` loads that PEM as a paramiko `pkey` — no certificate.

## Why this wave does not enable it

1. **Hub-held CA is a fleet mint.** Compromising the Hub already yields every vaulted per-target `SSH_PRIVATE_KEY`. That is bad. A CA private key is worse: the attacker mints **new** user certs for any principal and **new** host certs for any hostname until every host's `TrustedUserCAKeys` / host-CA trust is rotated. Per-target keys: after Hub recovery, dual-key rotate drops the stolen pubkeys; the attacker cannot mint a key the fleet will accept without writing `authorized_keys`. Host-key pinning (D-068) similarly: a stolen Hub does not let the attacker impersonate a host the operator already pinned. CircleCI 2023 extracted keys from a running process — short leaf TTLs do not help if the CA sits in that same process.

2. **The Hub is unattended.** Short-TTL certs need a signer at every Transport (collector, deploy, rotate, enroll). If the CA is Hub-resident, that is the fleet-mint problem. If the CA is offline (YubiKey / ceremony), every probe becomes a 2 a.m. USB touch — same shape as YubiKey KEK rung ②, already declined. There is no IdP to federate against. CISA/NSA's prescribed path is federation + phishing-resistant tokens, not a solo-operator Hub that is also the CA.

3. **The MUST control already landed.** Dual-key overlap, probe-before-revoke, T1 `ssh.rotate`, 90 d Beat `ssh-rotate-quarterly`, incomplete P1 `ssh-rotation-incomplete`, stale P2 `ssh-rotation-stale-key`, run-twice inspect-only (D-064). Overlap itself is not a Finding; a single-key clobber during overlap is the lockout D-064 forbids. B7's now-step is that playbook. Ephemeral-certs-from-an-IdP is the later research item; this fleet still has no IdP.

4. **Enablement is a fleet rewrite, not a setting.** New vault kind, catalog `sshd` drop-in, `SshTransport` cert path, enroll minting certs instead of Hub-minted Ed25519 (D-068 reverse), dual-CA rotate so a leaked CA is recoverable without lockout, KRL distribution. Inventing any of that here is enablement. AWS enroll this phase still injects a **public** Hub-minted key and pins provider-fetched host keys before Transport.

5. **Host CA fights the pin.** D-068 refuses TOFU. A Host CA the Hub holds lets a stolen CA mint a host cert for a MITM box that clients would accept. Replacing the pin with CA trust is a regression unless the Host CA is offline and the Hub never sees it — which then cannot enroll unattended.

## Dual-key stays (D-064 is not reversed)

This writeup does not replace `provision/ssh_rotate.py`. Overlap, probe-before-revoke, T1 `ssh.rotate`, 90 d Beat, incomplete P1 / stale P2, run-twice inspect-only remain. D-064 reverse ("SSH-CA landing in Phase 5 replacing this playbook") is unmet. D-068 reverse ("SSH-CA enablement replacing Hub-minted keys") is unmet. D-070 reverse is this eval **plus** a ruling that enablement is MUST — the ruling is the opposite.

## What would change the decision

Joseph ruling that SSH-CA enablement is MUST **and** the CA private key is not Hub-resident (offline ceremony / HSM / a real IdP that mints after WebAuthn) **and** a dual-CA rotate runbook that does not lock the operator out (D-064 shape for the CA itself) **and** unattended Transport still works (collector / deploy / rotate cannot wait for a USB touch). Until then the Hub does not generate a CA key, does not vault one, does not write `TrustedUserCAKeys`, and does not mint host or user certs.

## Explicitly not done

No CA key in the vault. No `Secret.Kind` for a CA. No `TrustedUserCAKeys` / `HostCertificate` in catalog or sshd drop-in. No change to `provision/ssh_rotate.py`. No certificate on `SshTransport`. No phase-5 due id (this writeup is not one; `P5-AWS-DEMO` must not claim enablement). Dual-key rotate stays. MUST demo does not wait.
