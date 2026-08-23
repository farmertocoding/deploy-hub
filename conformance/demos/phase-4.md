# Phase 4 exit demo — recorded (P4-SECURITY-DEMO)

**Date:** 2026-08-23 · **Branch:** `p4-t12` · **Recorded by:** Task 12
on BASE `a2030d4` (merge of MUST Tasks 0–10, including Task 6 SSH rotate)
plus the acceptance / demo files in this change. **T1 fakes only.** This is
not a live Cloudflare, live AWS KMS, live S3, YubiKey, or Playwright
success. No new token env was added. The retired zone-name env is not
used. `HUB_TEST_ZONE_SLUGS` remains the allowlist.

## What the milestone asked (design note §4)

Enroll WebAuthn security key + phone platform passkey → TOTP remains
fallback → T1 `target.delete` / `ssh.rotate` refuse without recent
WebAuthn touch and without type-the-name; after touch+name they run and
audit → TOTP-only session: T1 still refused with “add a passkey” → T3
rollback is one click and never step-up gated → idle timeout kills a
stolen session past 30 min → a repo with `deployhub.yaml` drill tree:
heuristic lines labelled and still blocking until wizard accept; `[proof]`
/ `.env` still block; root declaration refused; reason-edit invalidates
confirm id → TrafficStat z-score trip engages playbook through
`edge_protection_for` (FakeEdgeProtection in T1): Under-Attack set, IP
banned, P1 Finding + Sites AttackState + Home banner, auto-relax;
`refuse_if_attack` returns the named refuse; missing edge ref is
notify-only not silent → map Findings for r1–r5 → quarterly SSH rotate
run-twice with dual-key overlap (second run zero mutating Transport
calls) → BackupUnit list on Sites + test-now seals a dump with the
backup key, not the KEK; restore command block visible, no restore POST;
failed dump files P1 `hub-db-or-backup-failure` → `alerts` topic
unauthorized → compose parse proves Redis unpublished + requirepass +
JSON serializers → exhaust gate greps captured output → Tailscale poll
skip-only (no token) with dated waiver **or** FakeTailscale unknown-device
Finding → `KmsKEK` wrap/unwrap under moto; unconfigured `kms` refuses;
DEK cache survives a fake KMS blip; keyfile still boots tests.

`make conformance-4` is the phase-4 gate:
`python conformance/check.py --phase 4 --exclude-tier t2 --exclude-tier t3`.
`conformance-3` remains the all-tiers Phase 3 nightly gate. Live CF / KMS
/ S3 stay skipped-only + dated waiver, never a T1-sibling green. No paid
AWS. T4 Playwright is SLIP and was not run. YubiKey KEK rung ② is SLIP;
this record does not claim it. Live Object Lock is a Joseph interrupt;
this record does not claim a live S3 ship.

## The honest state of this host

T1. Fakes actually driven this session:

- `FakeHelper` (django-otp-webauthn protocol; no authenticator)
- `FakeEdgeProtection` (L5 playbook)
- `RotateTransport` / `FakeTransport` (SSH rotate dual-key; backup pg_dump fail)
- `FakeTailscale` (unknown-device Finding)
- `FakeKms` (DEK cache blip) and moto 5.x on `providers/kms.py` (wrap/unwrap)

The test-plane Cloudflare token env is unset. Tailscale vault ref
`HUB_TAILSCALE_API_TOKEN_REF` defaults empty. `VAULT_KMS_KEY_ID` is
empty; `VAULT_KEK_BACKEND` is not `kms` in tests. Multipass is not part
of this record. No Playwright.

## What actually landed (Tasks 0–10, T1)

This session re-ran the marked T1 source files on `a2030d4` before the
record files: **103 passed**, 0 skipped, across
`test_webauthn_t1.py`, `test_d012_reland.py`, `test_attack_playbook.py`,
`test_topology.py`, `test_ssh_rotate.py`, `test_backup_operator.py`,
`test_findings_api.py`, `test_redis_crown_jewel.py`,
`test_secrets_in_exhaust.py`, `test_tailscale_devices.py`,
`test_kms_kek.py`, `test_audit.py`, `test_makefile_nightly.py`,
`test_certs_phase_pin.py`, `test_d023_actions_not_required.py`,
`test_conformance_gate.py::test_tls_b2_hub_dns01_stays_phase_4`,
`test_drills.py::test_hub_down_still_refuses_to_claim_24h`.
Then the named acceptance file was written and its sixteen behavioural
clauses passed on those same fakes; the three record clauses stayed red
until this file existed. After this file:
`tests/acceptance/test_phase_4.py` **19 passed**, 0 skipped (T1 fakes).

### WebAuthn + T1 touch + idle

Enroll under `/api/auth/webauthn/` stores a confirmed security-key
credential and issues recovery codes once; the phone platform passkey is
a second confirmed credential. Login accepts WebAuthn *or* TOTP *or* a
recovery code. TOTP and recovery authenticate login, never T1 —
`hardware_touch_at` is written only by `POST /api/auth/webauthn/touch/`.
`target.delete` and `ssh.rotate` are T1: two passkeys, recent WebAuthn
touch, and type-the-name; after those they run and audit. A TOTP-only
session is refused with “add a passkey”. T3 rollback never takes
`RequireRecentTouch`; client `presentation()` keeps `stepUp: "none"`.
IdleTimeoutMiddleware enforces `HUB_SESSION_IDLE_TIMEOUT` (30 min).

### D-012 re-land

A `deployhub.yaml` drill tree labels heuristic `core.secret-scan` lines
and they still block until the operator accepts the content-keyed confirm
in the wizard. `[proof]` and `.env` stay blocking under an accepted
declaration. Declaring the scan root warns and downgrades nothing.
Editing the reason yields an id nobody has answered.

### L5 playbook (FakeEdgeProtection)

A TrafficStat z-score trip runs the playbook: Under-Attack then `ban_ip`,
P1 `attack-playbook-engaged:{zone.pk}`, Sites `AttackState`, Home
`AttackBanner`, pager click `{HUB_PUBLIC_URL}/#/findings/{id}`. Second
pass records zero EdgeProtection mutations. `refuse_if_attack` raises the
named refuse while engaged and returns None after auto-relax. Absent
`edge_token_ref` is notify-only, never a silent no-op.

### Topology r1–r5

`monitor/topology.py` files the C5 fingerprints from `graph_snapshot` plus
Site/Target/SiteInstance. No graph library.

### SSH rotate

Dual-key overlap: generate in-Hub, append both pubkeys via `put()`, probe
new, drop old, retarget, revoke old Secret. Never `ssh-keygen` on the
target. Second pass is probe-only. Beat `ssh-rotate-quarterly` is 90 d.
`ssh.rotate` is T1.

### Backup operator

Sites-detail list returns metadata only. Test-now seals with
`Secret.Kind.BACKUP_KEY`, Hub-local 0600 path, not the KEK. Restore is a
`<pre>` command block; no restore POST. Failed `pg_dump` files P1
`hub-db-or-backup-failure`.

### Leftover honesty

`alerts` is unauthorized; `findings` stays the one attention stream
(D-045 retired, D-061). Compose parse: Redis unpublished + `--requirepass`
+ JSON Celery serializers (SEC-B4). Exhaust gate greps captured pytest
stdout/stderr/log and Celery kwargs (SEC-69); `make log-scrub` stays the
source-scan. Local `audit()` prev_hash chain never blocks on S3; the
full-text SEC-B3 live-S3 P2 clause is not marked (Task 11 SLIP).

### Tailscale skip-unless **or** FakeTailscale

Empty `HUB_TAILSCALE_API_TOKEN_REF` writes CheckRun.Kind.TAILSCALE_DEVICES
SKIPPED, never SUCCEEDED. Dated skip-unless-configured waiver
`SEC-B8-TAILSCALE-DEVICE-POLL` stays. FakeTailscale files P2
`tailscale-unknown-device`. No live token env was invented.

### KmsKEK (moto / FakeKms)

Wrap/unwrap under moto on `providers/kms.py`. `VAULT_KEK_BACKEND=kms`
with empty `VAULT_KMS_KEY_ID` refuses. In-process DEK cache survives a
FakeKms blip. Keyfile remains the test/dev rung and does not defeat a
stolen Hub disk. `vault/` and the KMS tests do not import boto3. No live
AWS.

## Still outstanding — named, not greened

- `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven` **stays in WAIVERS.md**
  (D-042). The 24-hour form is a dated calendar item. This record is T1
  security-suite fakes. The REL-P2 duration is still not claimed. Not this
  phase.
- `TLS-B2-HUB-DNS01-UNPROXIED` stays the named **first slip**. Unproxied
  refusal stays (`UnproxiedCertUnsupported` / Sites-screen). Hub-central
  DNS-01 is waived, not verified. The full-text
  `SEC-B2-NO-DNS-TOKENS-ON-TARGETS` waiver stays.
- `HARNESS-T3-LE-STAGING` and `DNS-CF-T3-LIVE` stay waived
  (`no-test-zone-credentials`). Leftover Task 8 owns the LE line.
- `SEC-B8-TAILSCALE-DEVICE-POLL` skip-unless-configured stays while the
  vault ref is empty. T1 FakeTailscale is not a live poll.
- Task 11 SLIP (live S3 Object Lock, YubiKey KEK ②, tailnet-lock
  enablement writeup) is not this record.

## Acceptance transcription — real nodeids

`tests/acceptance/test_phase_4.py` (`@pytest.mark.acceptance(phase=4)`),
T1 fakes, this session:

- `::test_webauthn_security_key_and_phone_passkey_totp_fallback`
- `::test_t1_target_delete_and_ssh_rotate_need_touch_and_name`
- `::test_totp_only_session_refused_with_add_a_passkey`
- `::test_t3_rollback_is_one_click_and_never_step_up_gated`
- `::test_idle_timeout_kills_stolen_session_past_30_min`
- `::test_declared_drill_tree_blocks_until_wizard_accept`
- `::test_attack_playbook_fake_edge_and_never_scale`
- `::test_topology_r1_r5_findings`
- `::test_ssh_rotate_dual_key_run_twice`
- `::test_backup_list_test_now_command_block_and_p1`
- `::test_alerts_topic_unauthorized`
- `::test_compose_parse_redis_unpublished_requirepass_json`
- `::test_exhaust_gate_greps_captured_output`
- `::test_tailscale_skip_unless_or_fake_unknown_device`
- `::test_kms_kek_moto_refuse_cache_keyfile`
- `::test_audit_hash_chain_local_never_blocks_on_s3`
- `::test_rel_p2_24h_still_not_claimed`
- `::test_hub_central_dns01_stays_first_slip`
- `::test_conformance_4_excludes_t2_t3`

No `@pytest.mark.req` on `SEC-B2-NO-DNS-TOKENS-ON-TARGETS` or
`TLS-B2-HUB-DNS01-UNPROXIED`. No `@pytest.mark.req` on
`SEC-B3-AUDIT-HASH-CHAIN` (live S3 P2 is SLIP).

## Gates

`conformance-4` = `python conformance/check.py --phase 4 --exclude-tier t2 --exclude-tier t3`.
`conformance-3` stays all-tiers Phase 3. New phase-4 ids are tier-less.
`VALID_TIERS` is `{t1, t2, t3}` — t4 was not added. This record does not
claim `make review-round` or `make conformance-4` ran in this Task 12
session — those gates re-earn green from a fresh run-report. The proofs
this file records are the T1 pytest nodeids above.
