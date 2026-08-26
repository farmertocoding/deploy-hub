# Phase 5 exit demo — recorded (P5-AWS-DEMO)

**Date:** 2026-08-24 · **Branch:** `p5-t11` · **Recorded by:** Task 11
on BASE `7d9aeb7` (merge of MUST Tasks 0–9, plus Task 10 SSH-CA evaluation
writeup) plus the acceptance / demo files in this change. **T1 fakes only.**
This is not a live AWS, live Cloudflare, live Route 53, live SSM, live ECR,
or Playwright success. No new token env was added. Pinned allowlists remain
`HUB_TEST_AWS_ACCOUNT_IDS` and `HUB_TEST_AWS_REGIONS`.
`HUB_TEST_ZONE_SLUGS` remains the DNS allowlist.

## What the milestone asked (design note §4)

Settings AWS tab: empty `AWS_CREDENTIALS_REF` paints degraded, never
“Connected”; a write-only paste is observed (GetCallerIdentity + IAM
allowlist including groups) before any vault write; 201 never echoes keys;
`*` / `AdministratorAccess` / group-attached Admin / `NotAction` refuses
and files kind `aws-scope` fingerprint `aws-scope:{account_id}` with refs,
not secrets → under `HUB_TEST_MODE` + allowlisted account/region +
`purpose=test` tags, T1 `instance.create` shows `$0.05/h` (Fake) as
`T1Overlay.cost`, requires WebAuthn touch + type-the-name, Hub-mints the
SSH key (public-only inject, `ssh_key_ref` set before Transport), calls
`create_instance` with IMDSv2 hop-limit 1 and no public 22, pins
`host_key_fingerprint` before `provision_host`, stores `kind=aws_ec2` +
`provider_ref` → empty pin still refuses Transport → `target.delete` on
that row terminates (absent == success) then deletes; terminate failure
keeps the row; `instance.terminate` is T1 and does not leave `READY` →
Route 53 `dns_provider_for` fail-closed; `proxied=True` raises; L5 against
that zone is notify-only → `ensure_ship` with `registry=None` still
docker-loads; Fake registry requires TLS+auth and split creds → SSM pull
writes Get-only parameters under `/deploy-hub/{target.pk}/` and never
`AWS_ACCESS_KEY_ID` on the target → cloud reaper lists `purpose=test` and
terminates through the port (`CheckRun.Kind.AWS_REAPER`); Multipass reaper
stays prefix-only → empty allowlist / empty ref / default boto3 chain all
refuse → NAV is still six.

Record: `conformance/demos/phase-5.md`. `make review-round` twice clean
(Phase 5 minus live tiers). `make conformance-5` is the phase gate and
**excludes t2/t3**:
`python conformance/check.py --phase 5 --exclude-tier t2 --exclude-tier t3`.
Live AWS stays skipped-only, never a T1-sibling green. No invented token
env. No paid AWS.

## The honest state of this host

T1. Fakes actually driven this session:

- `FakeHelper` (django-otp-webauthn protocol; T1 touch on create/delete/terminate)
- `FakeCloudProvider` (enroll, terminate, cloud reaper, `$0.05/h` overlay)
- `FakeIam` (construction + daily allowlist, user and groups)
- `FakeSsm` (pull prefix + Get-only; no keys on the target env file)
- `FakeImageRegistry` (TLS+auth required; push cred ≠ pull cred)
- `FakeTransport` (enroll provision_host; SSM env-file puts)
- moto 5.x on `providers/ec2.py` (IMDSv2 hop-limit 1; default SG no public 22),
  `providers/route53.py` (fail-closed construct; `proxied=True` raises),
  `providers/ssm.py` (off-prefix Put refuses), and
  `providers/aws_creds.py` (explicit keys into the client, never the default chain)

`AWS_CREDENTIALS_REF` defaults empty. `HUB_TEST_MODE` is off unless a test
flips it. Account and region allowlists default empty (refuse live). No
Playwright. Multipass is not part of this record. No paid AWS.

## What actually landed (Tasks 0–9, T1)

This session re-ran the marked T1 source files on `9b4cd49` before the
record file: **162 passed**, 0 skipped, across
`test_aws_creds.py`, `test_aws_enroll.py`, `test_aws_terminate.py`,
`test_ec2_provider.py`, `test_route53_provider.py`,
`test_attack_playbook.py`, `test_image_registry.py`, `test_ssm.py`,
`test_cloud_reaper.py`, `test_aws_iam_audit.py`,
`test_makefile_nightly.py`, `test_d023_actions_not_required.py`,
`test_certs_phase_pin.py`, `test_ssh_rotate.py`,
`test_conformance_gate.py::test_valid_tiers_still_t1_t2_t3_only`,
`test_conformance_gate.py::test_tls_b2_hub_dns01_stays_phase_4`,
`test_drills.py::test_hub_down_still_refuses_to_claim_24h`.
Then the named acceptance file was written and its sixteen behavioural
clauses passed on those same fakes; the two record clauses stayed red
until this file existed. After this file:
`tests/acceptance/test_phase_5.py` **18 passed**, 0 skipped (T1 fakes).

### Settings AWS tab

Empty `AWS_CREDENTIALS_REF` GET `/api/v1/aws/connect/` returns
`connected: false` and names `HUB_AWS_CREDENTIALS_REF`. `AwsPanel` copy is
“not connected”; it never paints Connected. Paste is write-only.

### Observe-then-put

`observe_credentials` (GetCallerIdentity + IAM allowlist, user **and**
groups) runs before `vault.put`. An Admin paste is refused with no vault
row. A 201 names `account_id_last4` and region; the pasted keys never
echo.

### IAM refuse → aws-scope

`*` / `AdministratorAccess` / group-attached Admin / `NotAction` raise
`AwsScopeError` and file kind `aws-scope` fingerprint
`aws-scope:{account_id}` P2. Finding body carries the vault ref and
account, never secret material. Daily Beat `aws-iam-scope-daily` reuses
the same helper (`CheckRun.Kind.AWS_IAM_SCOPE`).

### T1 create + cost overlay

`FakeCloudProvider.estimate_hourly_cost` is `$0.05/h`. `T1Overlay.cost` is
required on `instance.create` and shown in words (“five cents per hour”)
before Confirm. `instance.create` is T1 (RequireRecentTouch HTTP +
type-the-name). TOTP does not write `hardware_touch_at`.

### Enroll pin (Fake) + IMDSv2 (moto)

Hub-mints Ed25519, vaults the private key, sets `ssh_key_ref` before
Transport, injects the public key only (`ssh-ed25519`, never PEM /
CreateKeyPair). `host_key_fingerprint` is pinned before `provision_host`.
Empty pin refuses Transport (no AutoAdd). Kind `aws_ec2` + `provider_ref`
(`i-…`) + Transport `host`. moto `RunInstances` sets
`MetadataOptions.HttpTokens=required` and hop-limit 1; default SG has no
public 22.

### Terminate / delete

`target.delete` on `aws_ec2` calls `terminate_instance` then drops the
row. Absent instance is success. Terminate failure files kind
`aws-terminate-failed` fingerprint `aws-terminate:{target.pk}` P1 and
**keeps** the row. `instance.terminate` is T1 labelled Terminate target
and does not leave `status=ready`.

### Route 53

`dns_provider_for` is fail-closed (empty ref, leftover vault row, name
mismatch). `proxied=True` raises and writes no A. L5 against a Route 53
zone is notify-only (`edge_protection_for` is None; AttackState
`notify_only`). Route 53 is DnsProvider, not EdgeProtection.

### ImageRegistry / SSM / reaper

`ensure_ship` with `registry=None` still `docker load`. `FakeImageRegistry`
refuses tls=False / auth=False / http; push cred ≠ pull cred, per-target.
SSM pull Puts `/deploy-hub/{target.pk}/KEY`; instance-profile policy is
`ssm:GetParameter*` on that prefix only; `AWS_ACCESS_KEY_ID` never lands
in the target env file. Cloud reaper lists `{purpose: test}` after the
D-066 wall, terminates through the port, writes `CheckRun.Kind.AWS_REAPER`.
`monitor/reaper.py` stays Multipass `hub-t3-` and boto3-free.

### Test-plane wall + NAV

Empty `AWS_CREDENTIALS_REF` refuses even with a leftover vault row.
Empty account or region allowlist refuses live under `HUB_TEST_MODE`.
`boto3.client` kwargs always carry both explicit keys; env session token
is not used. NAV is the six objects. `VALID_TIERS` stays `{t1, t2, t3}`.

## Still outstanding — named, not greened

- `TLS-B2-HUB-DNS01-UNPROXIED` stays **phase 4** and is marked. Hub-central
  DNS-01 T1 Fake landed. The TLS-B2 and full-text
  `SEC-B2-NO-DNS-TOKENS-ON-TARGETS` waivers are retired. Live Let's
  Encrypt stays skipped.
- SSH-CA is evaluation outstanding (`docs/ssh-ca-evaluation.md`, Task 10).
  Dual-key rotate stays. This record does not enable an in-Hub CA; it
  does not claim SSH-CA enablement.
- `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven` **stays in WAIVERS.md**
  (D-042). This record is T1 AWS-adapter fakes. The REL-P2 duration is
  still not claimed. Not this phase.
- Live AWS of any kind is a Joseph interrupt. This record does not claim
  a live IAM paste, live EC2, live Route 53, live SSM, or live ECR.
- T4 Playwright is out of scope. No Playwright.

## Acceptance transcription — real nodeids

`tests/acceptance/test_phase_5.py` (`@pytest.mark.acceptance(phase=5)`),
T1 fakes, this session:

- `::test_empty_ref_paints_degraded_not_connected`
- `::test_connect_observes_before_vault_put`
- `::test_connect_201_never_echoes_keys`
- `::test_iam_refuse_files_aws_scope`
- `::test_t1_create_shows_cost_fake_0_05`
- `::test_enroll_public_key_only_ssh_key_ref_before_transport`
- `::test_pin_before_transport`
- `::test_empty_pin_refuses_transport`
- `::test_target_delete_terminates_then_deletes`
- `::test_terminate_failure_does_not_delete_row`
- `::test_instance_terminate_is_t1`
- `::test_route53_fail_closed_proxied_raises_l5_notify_only`
- `::test_ensure_ship_none_docker_loads`
- `::test_fake_registry_tls_auth_split_creds`
- `::test_ssm_get_only_no_target_keys`
- `::test_cloud_reaper_vs_multipass`
- `::test_empty_allowlist_ref_and_default_chain_refuse`
- `::test_nav_stays_six`

No `@pytest.mark.req` on `P5-AWS-DEMO` (verify: demo is this file). No
MUST id marked on a skip-unless or live test.

## Gates

`conformance-5` = `python conformance/check.py --phase 5 --exclude-tier t2 --exclude-tier t3`.
`conformance` (review-round) is the same recipe. `conformance-4` stays
phase 4 minus live. `conformance-3` stays all-tiers Phase 3. New phase-5
ids are tier-less. `VALID_TIERS` is `{t1, t2, t3}` — t4 was not added.
This record does not claim `make review-round` or `make conformance-5`
ran in this Task 11 session — those gates re-earn green from a fresh
run-report. The proofs this file records are the T1 pytest nodeids above.
