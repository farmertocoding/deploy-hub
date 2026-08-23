# Phase 5 Design Note — AWS adapters (T1 moto)

**Phase:** 5 per §I (Azure is Phase 7 / V11; partner is 5.5 / U1)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-23 · **Seat:** Grok 4.6
**Revision:** r2 — design panel MERGE-AFTER-FIXES (Architect + Security + QE). Required fixes: C12 fingerprints in the task list; Task 4/9 wait for Task 1; SSM path `{target.pk}`; v1 URL pins; §3 one-sentence texts; IAM group inspect + `NotAction`/service-star/escalation; Hub-minted SSH public-only; `ensure_ingress_rules` refuses public 22; terminate failure keeps the Target row; Task 0 claims `core/aws_views.py`. §7 is binding.
**Estimate:** ~1 wk T1. Protective cut: **D-065**. Phases 0–4 MUST are on `master` @ `0788ac2`. DNS-01, live KMS, live S3 stay Phase 4 slips. **Do not invent `HUB_TEST_CF_TOKEN` or `HUB_TEST_AWS_TOKEN`. `HUB_TEST_DNS_ZONE` stays retired.**
**Branch:** these two docs land on **`p5-design`**; Implementers cut task branches from it. Never implement on `master`. Sensitive-path merges go through the recorded panel vote.
**Closed schema wave:** `0011_phase4.py` stays closed. Phase 5 adds **one** Hub migration, `0012_phase5.py`: `Target.Kind.AWS_EC2` + nullable `Target.provider_ref` (`CharField(max_length=64, null=True, blank=True)`). Python-only `DnsAccount.Provider.ROUTE53`. No new Hub tables. No `NetworkZone.kind`. No `CloudAccount`. No `Site.tier`. **Task 1 is the only `core/models.py` writer this phase.** Later tasks do not edit it.
**Panel:** §7 is binding. An Implementer who invents a path, env, Finding fingerprint, action id, or gate shape that §7 does not name is implementing the wrong design.

## 1. What lands this phase

Phase 4 finished the security suite. Phase 5 is the D4 promise: **provisioning + DNS adapters**, plus the §E2 / §6.9 T1 seams. Downstream deploys / reconcile / monitor stay cloud-agnostic via ports. The stale V11 sentence (“Phase-5 week = adopt + N1”) is discarded: adopt is 3b, N1 is Phase 2.

### 1.1 MUST

1. **EC2 adapter** `providers/ec2.py` implementing `CloudProvider`. `cloud_provider_for` in `providers/registry.py` is the only constructor (fail-closed like `dns_provider_for`). T1 moto helper `mock_aws_ec2` lives in that module. `FakeCloudProvider` remains the test default. `ensure_ingress_rules` refuses 22 from `0.0.0.0/0` and `::/0`.
2. **Route 53 adapter** `providers/route53.py` implementing **`DnsProvider` only**. No `EdgeProtection`. `upsert_record(..., proxied=True)` raises. L5 against a Route 53 zone is notify-only.
3. **Enroll:** Hub-mints a per-target Ed25519, `vault.put` `SSH_PRIVATE_KEY`, set `ssh_key_ref` **before** any Transport. Inject **public key only** (UserData `ssh_authorized_keys` or `ImportKeyPair`). Never `CreateKeyPair`. Never Hub AWS creds / private key / SSM values in UserData. Then `cloud_provider_for` → `create_instance` → pin returned host keys onto `Target.host_key_fingerprint` **before** any `Transport` → store `kind=aws_ec2`, `provider_ref`, `host` = Transport address (tailnet IP/MagicDNS preferred, or public IP with SG 22 **only** from Hub egress — never world-open 22) → same §7.1 `provision_host`. Empty pin remains refuse (SEC-68).
4. **Registry shipping** as a capability/config flip of `ensure_ship`. New `ImageRegistry` port + `image_registry_for`. docker load stays default. Fake registry: TLS + auth; push cred ≠ per-target pull-only cred. ECR boto3, if any, under `providers/image_registry.py` — never `providers/registry.py`.
5. **SSM pull** T1 fake in `providers/ssm.py`. Push (`_put_env_file`) stays default. Flip is site/manifest `secrets_mode: push|ssm_pull`, **not** `Site.tier`. Instance profile Get-only on `/deploy-hub/{target.pk}/*`. Never static AWS keys on a target.
6. **AWS test-plane wall:** `HUB_TEST_MODE` + `purpose=test` tags + `HUB_TEST_AWS_ACCOUNT_IDS` + `HUB_TEST_AWS_REGIONS`. Credentials: `HUB_AWS_CREDENTIALS_REF` → `AWS_CREDENTIALS_REF` default `""`. Explicit keys into `boto3.client`. Never the default chain. Empty ref refuses. No `HUB_TEST_AWS_TOKEN`.
7. **IAM allowlists** at construction **and** a daily audit. Inspect user attached+inline **and** group attached+inline (and a present permission boundary). Missing user or group inspect = refuse. Refuse `*` / `AdministratorAccess` / `NotAction` / `ec2:*` / `ssm:*` / `iam:*` / privilege-escalation verbs / off-prefix SSM / off-zone Route 53.
8. **T1 friction:** `instance.create` and `instance.terminate` are T1 (`RequireRecentTouch` + type-the-name). `target.delete` on `aws_ec2` terminates then deletes **only after terminate succeeds** (absent == success). Terminate failure files C12 and **keeps the row**. `instance.terminate` must not leave `status=ready`. Route 53 upsert stays T2 `dns.change`. `ssh.rotate` stays T1. Dual-key rotate stays (D-064).
9. **Operator surface without a 7th NAV item.** Settings **AWS** tab (Cloudflare-connect shape). Cost from `estimate_hourly_cost` is `T1Overlay.cost` on create (required, not optional). F8 `enroll-empty` / `enroll-error` / `enroll-degraded`. Copy says Target, never “instance”.
10. **Cloud reaper** consumes `CloudProvider.list_tagged_instances` + `terminate_instance` from `monitor/cloud_reaper.py`. Leave `monitor/reaper.py` Multipass-only (no boto3 there). Weekly drill plants a Fake `purpose=test` instance and writes `CheckRun.Kind.AWS_REAPER`.
11. **Honesty:** Task 0 bumps `PART-K1` / `PART-K2` / `PART-K6` to `phase: 5.5` (do not implement §K; do not waive). Pin `boto3` in `requirements.txt`; moto stays `requirements-dev`. `vault/` and `tests/` do not import boto3/moto.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| T1 moto EC2 + Route 53 + enroll pin + IAM construction | **MUST** |
| ImageRegistry port + Fake TLS/auth; docker load default | **MUST** |
| SSM T1 fake; push default; no keys on target | **MUST** |
| Test-plane wall + cloud reaper on the CloudProvider port | **MUST** |
| Settings AWS tab + cost overlay + F8 enroll states | **MUST** |
| `instance.create` / `instance.terminate` T1; `target.delete` terminates on success | **MUST** |
| `0012_phase5.py`; PART-K → 5.5; `conformance-5` minus live tiers | **MUST** |
| SSH-CA design writeup | **named first slip.** Evaluation, not enablement. Dual-key stays. |
| Live EC2 / Route 53 / SSM / ECR / S3 / KMS | **Joseph interrupt** |
| IAM live paste against a real account | **SLIP** if it implies live keys; T1 Settings tab + refuse-unless is MUST |
| T3 parametrized over AWS (§G) | **Joseph / not this wave** |
| Azure, partner/MCP, scaler, DNS-01, N1, adopt, restore UI, Router Advisor, 7th NAV | **OUT** |

## 2. Interfaces / tables that change

**Migration `0012_phase5.py` (Target only) — Task 1 owns this file and `core/models.py` for the whole phase:**
- `Target.Kind.AWS_EC2 = "aws_ec2"`.
- Nullable `Target.provider_ref` (`CharField(max_length=64, null=True, blank=True)` — CloudProvider instance id, e.g. `i-…`). SSH rows stay null.
- Python-only `DnsAccount.Provider.ROUTE53 = "route53"`. If makemigrations emits an AlterField on `DnsAccount.provider` for the new choice, fold it into `0012` — still one wave, no new table.
- Python-only `CheckRun.Kind`: `AWS_IAM_SCOPE = "aws_iam_scope"`, `AWS_REAPER = "aws_reaper"`. Later tasks do **not** edit `core/models.py`.

**`CloudProvider.create_instance` return (pin, update Fake):** `{id, state, public_ip, host_key_fingerprint}` plus optional raw `host_keys`. Fingerprint is whatever `paramiko.PKey.fingerprint` equality `PinnedHostKeyPolicy` already uses.

**New port on `providers/base.py`:** `ImageRegistry` (`push`, `pull_spec` per target, `capabilities` includes `tls` and `auth`). `ensure_ship` takes `desired["registry"]` or `None`.

**ACTION_TIERS:** add `instance.create` and `instance.terminate` as T1. Do not move `dns.change`. Do not add a 7th NAV item. Labels say “Create target” / “Terminate target”. `T1Overlay` takes `cost`; `instance.create` passes it; other T1 ids omit it.

**HTTP (v1, not `core/urls.py` which is `/api/auth/`):**
- `POST /api/v1/aws/connect/` — `core/aws_views.py` included from `core/zone_urls.py` (same `api/v1/` include as Cloudflare connect).
- `POST /api/v1/instance/create/` — on `hub/urls.py` beside the other T1 target routes.
- `POST /api/v1/targets/<int:pk>/terminate/` — on `hub/urls.py` beside `targets/<pk>/delete/`.

**Gates:** `make conformance-5` = `python conformance/check.py --phase 5 --exclude-tier t2 --exclude-tier t3`. `make review-round` uses that via `conformance`. `conformance-4` stays phase 4 minus live. `conformance-3` stays all-tiers Phase 3. No `t4`. No all-tiers 5.

## 3. Applicable registry reqs

**Task 0 only — phase bump, `text:` / `text_hash:` untouched:** `PART-K1-ZERO-INBOUND-HUB` · `PART-K2-REPLAY-AT-HUB` · `PART-K6-NO-INTERNAL-ACTIONS` → `phase: 5.5`.

**New (Task 0).** Copy these fields; do not invent. No `tier:` key. `source: phase-5-design-note.md §3`. SCAN-M4: do not hang full-text §I Phase 5 / §D5 (Azure, SSH-CA enablement, Key Vault, T3-aws) on moto tests. `text_hash:` is computed by Task 0 (`conformance/check.py --print-text-hashes`), not invented here.

- `AWS-EC2-ADAPTER` — `phase: 5`, `verify: test`. `text:` `providers/ec2.py` implements CloudProvider; `cloud_provider_for` is the only constructor; T1 `mock_aws_ec2`; RunInstances sets IMDSv2 hop-limit 1; default SG has no public 22.
- `AWS-R53-ADAPTER` — `phase: 5`, `verify: test`. `text:` `providers/route53.py` implements DnsProvider only; `proxied=True` raises; class is not EdgeProtection; L5 against that zone is notify-only.
- `AWS-ENROLL-PIN` — `phase: 5`, `verify: test`. `text:` pin `host_key_fingerprint` before any Transport; store `kind=aws_ec2` + `provider_ref`; empty pin refuses.
- `AWS-TEST-PLANE` — `phase: 5`, `verify: test`. `text:` `HUB_TEST_MODE` + `purpose=test` + `HUB_TEST_AWS_ACCOUNT_IDS` + `HUB_TEST_AWS_REGIONS`; explicit vault keys into boto3; empty ref / empty allowlist / default chain refuse; no `HUB_TEST_AWS_TOKEN`.
- `AWS-IAM-ALLOWLIST` — `phase: 5`, `verify: test`. `text:` construction and daily audit refuse `*` / `AdministratorAccess` / off-prefix SSM / off-zone Route 53; missing inspect refuses; Finding body is refs.
- `AWS-SSM-PULL` — `phase: 5`, `verify: test`. `text:` T1 fake in `providers/ssm.py`; push stays default; instance profile Get-only on `/deploy-hub/{target.pk}/*`; never `AWS_ACCESS_KEY_ID` on the target.
- `AWS-IMAGE-REGISTRY` — `phase: 5`, `verify: test`. `text:` `ImageRegistry` port + `image_registry_for`; docker load remains default; Fake requires TLS+auth and split push/pull creds; ECR boto3 only under `providers/image_registry.py`.
- `AWS-INSTANCE-T1` — `phase: 5`, `verify: test`. `text:` `instance.create` and `instance.terminate` are T1; `target.delete` on `aws_ec2` terminates then deletes.
- `UX-P5-AWS-OPERATOR` — `phase: 5`, `verify: test`. `text:` Settings AWS tab (degraded, not Connected, when ref empty); cost on the T1 overlay; F8 enroll-empty/error/degraded; NAV stays six; copy says Target.
- `P5-AWS-DEMO` — `phase: 5`, `verify: demo`, `demo: conformance/demos/phase-5.md`. `text:` demo record names the MUST path in design note §4; no live AWS, no SSH-CA enablement, no DNS-01.

**Waivers:** Task 0 waives **nothing that is MUST**. Do not retire `TLS-B2-HUB-DNS01-UNPROXIED`, `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`, `HARNESS-T3-LE-STAGING`, `DNS-CF-T3-LIVE`, or `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven`. Do not register a live-AWS MUST id. `failed` / `not-collected` are unwaiable. SSH-CA writeup is not a due id.

## 4. Exit demo

Settings AWS tab: empty `AWS_CREDENTIALS_REF` paints degraded, never “Connected”; a write-only paste is observed (GetCallerIdentity + IAM allowlist including groups) before any vault write; 201 never echoes keys; `*` / `AdministratorAccess` / group-attached Admin / `NotAction` refuses and files kind `aws-scope` fingerprint `aws-scope:{account_id}` with refs, not secrets → under `HUB_TEST_MODE` + allowlisted account/region + `purpose=test` tags, T1 `instance.create` shows `$0.05/h` (Fake) as `T1Overlay.cost`, requires WebAuthn touch + type-the-name, Hub-mints the SSH key (public-only inject, `ssh_key_ref` set before Transport), calls `create_instance` with IMDSv2 hop-limit 1 and no public 22, pins `host_key_fingerprint` before `provision_host`, stores `kind=aws_ec2` + `provider_ref` → empty pin still refuses Transport → `target.delete` on that row terminates (absent == success) then deletes; terminate failure keeps the row; `instance.terminate` is T1 and does not leave `READY` → Route 53 `dns_provider_for` fail-closed; `proxied=True` raises; L5 against that zone is notify-only → `ensure_ship` with `registry=None` still docker-loads; Fake registry requires TLS+auth and split creds → SSM pull writes Get-only parameters under `/deploy-hub/{target.pk}/` and never `AWS_ACCESS_KEY_ID` on the target → cloud reaper lists `purpose=test` and terminates through the port (`CheckRun.Kind.AWS_REAPER`); Multipass reaper stays prefix-only → empty allowlist / empty ref / default boto3 chain all refuse → NAV is still six.

Record: `conformance/demos/phase-5.md`. `make review-round` twice clean (Phase 5 minus live tiers). `make conformance-5` is the phase gate and **excludes t2/t3**. Live AWS stays skipped-only, never a T1-sibling green. No invented token env. No paid AWS.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

Not open `DECISION:` blockers. Irreversible/spend: live AWS member account, live EC2/R53/SSM/ECR/S3/KMS are Joseph interrupts. MUST does not enable them.

- **D-065** Protective cut — T1 EC2 + Route 53 + enroll pin + registry/SSM seams + AWS test-plane wall; live AWS off; Azure/partner/scaler/N1/adopt/DNS-01 out; PART-K → 5.5; SSH-CA eval is first slip.
- **D-066** Vault-ref `HUB_AWS_CREDENTIALS_REF` → `AWS_CREDENTIALS_REF` default `""`. Explicit keys into boto3. Never default chain. Test plane = `HUB_TEST_MODE` + `purpose=test` + `HUB_TEST_AWS_ACCOUNT_IDS` + `HUB_TEST_AWS_REGIONS`. No `HUB_TEST_AWS_TOKEN`.
- **D-067** IAM allowlists; construction + daily audit inspect user **and** group attached+inline (permission boundary if present). Missing user or group inspect refuses. Refuse `*` / `AdministratorAccess` / `NotAction` / `ec2:*` / `ssm:*` / `iam:*` / `iam:CreateAccessKey` / `iam:AttachUserPolicy` / `iam:PutUserPolicy` / `iam:PassRole` on `*` / `sts:AssumeRole` / off-prefix SSM / off-zone Route 53.
- **D-068** `create_instance` returns provider-fetched host keys; pin `Target.host_key_fingerprint` before any Transport; Hub-minted per-target Ed25519, public-only inject, `ssh_key_ref` set before Transport; IMDSv2 + hop-limit 1; 22 not public-by-default; `ensure_ingress_rules` refuses 22 from `0.0.0.0/0` and `::/0`. Empty pin remains refuse. No Hub AWS creds in UserData.
- **D-069** SSM is `providers/ssm.py`; push stays default; flip is site/manifest capability not `Site.tier`; instance profile Get-only on `/deploy-hub/{target.pk}/*`; never static AWS keys on a target.
- **D-070** SSH-CA this phase is a written evaluation only. Dual-key rotate stays (D-064).
- **D-071** `conformance-5` / review-round = `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-4` stays phase 4 minus live. No `t4`. No all-tiers 5. FakeCloudProvider remains test default.
- **D-072** One Hub wave `0012_phase5.py`: `Target.Kind.AWS_EC2` + nullable `Target.provider_ref`. Python-only `DnsAccount.Provider.ROUTE53`. No new tables. `0011` stays closed. Task 1 is the only `core/models.py` writer.
- **D-073** `ImageRegistry` port + `image_registry_for`. `ensure_ship` takes that port or None. docker load remains default. ECR boto3, if any, under `providers/image_registry.py` — never `providers/registry.py`.
- **D-074** `instance.create` and `instance.terminate` are T1 (RequireRecentTouch + type-the-name). `target.delete` on `aws_ec2` terminates then deletes **only after terminate succeeds** (absent == success). Terminate failure files C12 and does **not** delete the row. `instance.terminate` must not leave `status=ready`. Route 53 upsert stays T2.

## 6. Out of scope (explicitly)

Azure adapter · partner intake / MCP · overflow scaler (the refuse gate stays) · Hub-central DNS-01 · restore UI · Router Advisor · 7th NAV item · Cloud/Instances/Registry/SSM consoles · N1 recreate/volumes · 3b adopt · `NetworkZone.kind` / `aws_vpc` · `Site.tier` · a `CloudAccount` table · SSH-CA **enablement** · live AWS of any kind · LocalStack · `t4` · all-tiers 5 · inventing `HUB_TEST_CF_TOKEN` / `HUB_TEST_AWS_TOKEN` · restoring `HUB_TEST_DNS_ZONE` · boto3 in `vault/` or `tests/` · implicit default credential chain · mandatory `connect_aws` first-run item · UI copy that calls a Target an “instance”.

**May slip without failing the MUST demo:** SSH-CA writeup (first) · live IAM paste against a real account · T3-on-AWS · fake S3 / live KMS leftovers from Phase 4. **Not** slip-able: T1 moto EC2 + Route 53, enroll pin, IAM construction refuse (including groups), test-plane wall, cloud reaper on the port, Settings AWS tab + cost overlay + F8, T1 create/terminate, `target.delete` terminates on success, ImageRegistry Fake TLS/auth, SSM Get-only fake, `0012`, PART-K bump, `conformance-5` minus live tiers.

## 7. Closed answers (panel — do not reopen)

### C1 — Protective cut / PART-K

MUST is T1 moto / FakeCloudProvider only. Task 0 bumps PART-K1/K2/K6 to `phase: 5.5` and does not implement §K and does not waive them. First slip = SSH-CA **writeup**. Live AWS is Joseph. Azure is Phase 7. Stale V11 adopt+N1 sentence is out.

### C2 — Schema

`0012` = `Target.Kind.AWS_EC2` + nullable `Target.provider_ref` (`max_length=64`). `DnsAccount.Provider.ROUTE53` is a Python choice (fold AlterField into `0012` if generated). CheckRun kinds `aws_iam_scope` and `aws_reaper` land in Task 1. No new tables. `0011` closed. Task 1 is the only `core/models.py` writer. VPC/subnet/SG live in the `create_instance` spec, not `NetworkZone.kind`. AWS creds are existing `Secret.Kind.CLOUD_CREDENTIAL`.

### C3 — Credentials / test plane

Env `HUB_AWS_CREDENTIALS_REF` → setting `AWS_CREDENTIALS_REF` default `""`. Vault shape is JSON **exactly** `{access_key_id, secret_access_key}` (`owner_type="aws"`, `owner_id` = the ref). Extra keys / session tokens refused. Constructors pass those two into `boto3.client(...)` and **never** omit them (no default chain, no `~/.aws`, no instance-profile-on-the-Hub). Empty ref refuses even if a leftover vault row exists.

Test plane is quadruple-keyed: `HUB_TEST_MODE` **and** `purpose=test` tags **and** account id on `HUB_TEST_AWS_ACCOUNT_IDS` **and** region on `HUB_TEST_AWS_REGIONS` (comma lists, default `""` → refuse live). Outside `HUB_TEST_MODE`, a test-purpose tagged call refuses. Route 53 **zone names** still use `HUB_TEST_ZONE_SLUGS`. `sts:GetCallerIdentity` at construction. Prod keeps `HUB_TEST_MODE = False`.

Settings AWS connect (Cloudflare-connect shape): `POST /api/v1/aws/connect/` in `core/aws_views.py`. Observe pasted keys **before** any vault write (throwaway explicit-key client, not the product client). IAM overscope / inspect-failure refuses and files a Finding. On pass, `vault.put` under `owner_id=settings.AWS_CREDENTIALS_REF`. If the setting is empty, connect refuses with degraded copy (“set `HUB_AWS_CREDENTIALS_REF`”); it does not invent a token env and does not paint Connected. 201 never contains key material. Success body may name account id last-4 and region.

### C4 — IAM allowlists (load-bearing)

Hub user is not `AdministratorAccess` and not `Action: "*"`. Construction **and** daily Beat audit parse **user** attached+inline **and** `ListGroupsForUser` + each group's attached+inline, plus a present permission boundary, and refuse a superset. Missing user inspect **or** missing group inspect = refuse (fail-closed). Refuse `NotAction`. Refuse Hub-user `ec2:*` / `ssm:*` / `iam:*`. Refuse `iam:CreateAccessKey`, `iam:AttachUserPolicy`, `iam:PutUserPolicy`, `iam:PassRole` on `*`, `sts:AssumeRole`.

Pinned Hub-user allowlist:
- `sts:GetCallerIdentity`
- `iam:GetUser`, `iam:ListAttachedUserPolicies`, `iam:GetPolicy`, `iam:GetPolicyVersion`, `iam:ListUserPolicies`, `iam:GetUserPolicy`, `iam:ListGroupsForUser`, `iam:ListAttachedGroupPolicies`, `iam:ListGroupPolicies`, `iam:GetGroupPolicy` (self-inspect only; missing inspect = refuse)
- EC2: `RunInstances`, `Describe*`, `TerminateInstances`, `CreateTags`, `GetConsoleOutput`, `CreateImage`, SG mutate for `ensure_ingress_rules`. Region condition = allowlist
- Route 53: `GetHostedZone`, `ListResourceRecordSets`, `ChangeResourceRecordSets`, `GetChange` on **that** `DnsZone.provider_zone_id` only
- Hub SSM: `PutParameter` / `GetParameter*` / `DeleteParameter` / `AddTagsToResource` on `/deploy-hub/*` only
- `iam:PassRole` only on the SSM Get-only instance-profile role ARN if one is attached — never `*`

Instance profile (on the target, not the Hub user): `ssm:GetParameter*` on `/deploy-hub/{target.pk}/*` only — no Put, no `ec2:*`, no `iam:*`. Do not attach the Hub user as the instance profile.

T1 tests hand a policy document to the helper; `tests/` do not import boto3. Finding body has **refs**, never the secret.

### C5 — Enroll / pin / IMDS / SG / first-login SSH

`create_instance(spec)` kwargs **must** include `MetadataOptions.HttpTokens=required` and `HttpPutResponseHopLimit=1`. Default SG: **22/tcp not `0.0.0.0/0` and not `::/0`**. `ensure_ingress_rules` refuses 22/tcp (and ssh) from `0.0.0.0/0` and `::/0` — including “temporarily.” Public 80/443 only when Tunnel is not the mode. Under `HUB_TEST_MODE`, spec without `tags.purpose=test` refuses.

First-login SSH: mint per-target Ed25519 in-Hub (same as `ssh.rotate`); `vault.put` `SSH_PRIVATE_KEY`; set `Target.ssh_key_ref` **before** any Transport. Inject **public key only** (cloud-init UserData `ssh_authorized_keys` or `ImportKeyPair` of the pubkey). **Never** `CreateKeyPair`. **Never** UserData/IMDS the private key, Hub `CLOUD_CREDENTIAL`, or SSM parameter values.

`Target.host` is the Transport address: tailnet IP/MagicDNS after UserData `tailscale up` (preferred, §7.1.0), **or** public IP with SG 22 **only** from Hub egress. Never world-open 22.

Host keys: provider-fetched (`GetConsoleOutput` on EC2; Fake returns a fingerprint immediately). Bounded wait, then **refuse**, never TOFU / AutoAdd. Pin `Target.host_key_fingerprint` before `provision_host` / any `Transport`. Empty pin stays refuse.

Return dict: `{id, state, public_ip, host_key_fingerprint}` (+ optional `host_keys`). Update `FakeCloudProvider` so smoke `create_instance` still has `id` and terminate stays idempotent.

`create_image` is T1-fake (returns an id). AMIs are not a secret store. No live `CreateImage`.

`estimate_hourly_cost`: Fake returns `0.05`. EC2 adapter uses a tiny in-module table (t3.micro / t3.small), not the live Price List. `T1Overlay.cost` shows the number (symbol + words, not color-only) **before** Confirm on `instance.create`. Other T1 ids omit `cost`. Unconfigured/error estimate refuses create — never `$0` as “free”. Existing kind `budget-cap-hit` fires when a configured `HUB_AWS_HOURLY_BUDGET_USD` → `AWS_HOURLY_BUDGET_USD` (default `""` = show, do not file) is exceeded. The $10 member-account alarm is Joseph’s AWS console, not a Hub token env.

### C6 — Constructors

- `cloud_provider_for(...)` in `providers/registry.py` — only CloudProvider constructor.
- Route 53 branch of `dns_provider_for` — same fail-closed as Cloudflare; loads `CLOUD_CREDENTIAL` (not `API_TOKEN`); `DnsAccount.dns_token_ref` holds the same owner-id as `AWS_CREDENTIALS_REF` (refuse if they differ; never copy CLOUD_CREDENTIAL into an `API_TOKEN` row).
- `image_registry_for(...)` in `providers/registry.py`.
- `ssm_for(target)` in `providers/registry.py`.
- `edge_protection_for` stays Cloudflare-only: absent edge ref → `None` → notify-only; present ref on a non-CF provider raises. Never a silent no-op. DNS client never loads `edge_token_ref`; edge client never loads the AWS/DNS credential.

Shared loader: `providers/aws_creds.py` (boto3 allowed). `deploys/`, `vault/`, `monitor/`, `provision/`, `tests/` never import boto3.

### C7 — Route 53 / L5 / DNS-01

Route 53 class is not an `EdgeProtection`. `capabilities()` omits `proxied`. `upsert_record(..., proxied=True)` raises (must not silently write an unproxied A). Public proxied sites stay Cloudflare. Unproxied Route 53 HTTPS waits on DNS-01 (still the Phase 4 slip). EC2 targets may host Cloudflare-proxied sites — CloudProvider ⊥ DnsProvider. L5 against a Route 53 `DnsZone` files notify-only (existing playbook). Do not share the AWS credential as an edge token.

### C8 — SSM / ImageRegistry

Manifest/desired: `secrets_mode: push | ssm_pull` default `push`. `ship_mode: load | registry` default `load`. No Site column. No 7th NAV.

SSM paths are `/deploy-hub/{target.pk}/…` only (not a slug). Hub SSM Put/Get/Delete/AddTags on `/deploy-hub/*`. Instance-profile Get-only on `/deploy-hub/{target.pk}/*`. Push remains `_put_env_file`. Pull never writes `AWS_ACCESS_KEY_ID` / Hub IAM user keys onto the target. Tokens and parameter **values** never in Finding / CheckRun / log / task arg / `AuditEvent.detail`.

`ImageRegistry` port: `push(tag, archive)`, `pull_spec(tag, *, target) -> {url, username, password}` (pull-only, per-target), `capabilities() >= {tls, auth}`. Fake must model TLS + auth + split push vs pull. `ensure_ship`: `registry is None` → today’s docker load; else push then target `docker pull` with pull-only cred. Pull login via 0600 cred file or stdin, never password-on-argv. ECR boto3 only in `providers/image_registry.py`.

### C9 — T1 ids / UX / F8 / HTTP

ACTION_TIERS ids are `instance.create` and `instance.terminate` (D-074). Labels: “Create target” / “Terminate target”. UI copy never says “instance” (D9). `confirm_name` = intended host on create, `target.host` on delete/terminate. T1 = WebAuthn touch + type-the-name; TOTP does not write `hardware_touch_at`. Enroll lives on **Targets**, not a new route. Empty state stays one sentence + one button: provision CLI if `AWS_CREDENTIALS_REF` is empty, else Create target. Settings tabs gain `{id: "aws", label: "AWS"}` beside Cloudflare. NAV stays the six. Do not add `connect_aws` to `checklist.ITEM_IDS`. F8 seed+render: `enroll-empty`, `enroll-error`, `enroll-degraded` (+ cost-visible overlay) against Targets/Settings/Findings. `?sim=` mounts Shell. `burst-ec2-1` `kind: aws_ec2` becomes a legal Kind after Task 1; Task 5 adds a test-purpose `aws-use1` zone (or retargets that seed row) so the fixture loads.

Pinned paths: `POST /api/v1/aws/connect/`, `POST /api/v1/instance/create/`, `POST /api/v1/targets/<int:pk>/terminate/`. `core/urls.py` is `/api/auth/` — do not hang v1 AWS routes there.

### C10 — Gates / env names / moto

`conformance` + `conformance-5` = `--phase 5 --exclude-tier t2 --exclude-tier t3`. Leave `conformance-4` as today’s recipe. Leave `conformance-3` all-tiers 3. `nightly-gates` still uses `conformance-3`. No all-tiers 5. No `t4` in `VALID_TIERS`. New ids have **no `tier:` key**. Do not stub `conformance/demos/phase-5.md` in Task 0 (missing = uncovered).

Pinned names: `HUB_AWS_CREDENTIALS_REF`, `HUB_TEST_AWS_ACCOUNT_IDS`, `HUB_TEST_AWS_REGIONS`, `HUB_AWS_HOURLY_BUDGET_USD`. **Do not invent `HUB_TEST_AWS_TOKEN` / `HUB_TEST_AWS_ACCESS_KEY_ID` / `HUB_TEST_CF_TOKEN`.** Do not restore `HUB_TEST_DNS_ZONE`. `HUB_TEST_ZONE_SLUGS` stays the DNS/NetworkZone allowlist.

moto 5.x helpers `mock_aws_ec2` / `mock_aws_route53` / `mock_aws_ssm` live in the matching provider modules (dummy static creds inside, copy `mock_aws_kms`). Not LocalStack. Extend the kms-style “this test file has no boto3/moto import” grep to the new test modules. `test_explicit_keys_passed_into_client_never_default_chain` inspects `boto3.client(...)` kwargs (both keys present; `aws_session_token` not taken from env) — a constructor that omits them fails even inside moto.

### C11 — Reaper / delete / run-twice

`monitor/reaper.py` stays Multipass `hub-t3-` prefix-only. `monitor/cloud_reaper.py` takes a `CloudProvider`, lists `{purpose: test}` only after the D-066 wall, terminates (absent == success). No-op when `HUB_TEST_MODE` is False. Weekly drill plants a FakeCloudProvider `purpose=test` instance, asserts gone, and writes `CheckRun.Kind.AWS_REAPER`. Do not claim `HARNESS-REAPER-TEST-PLANE` covers AWS.

`instance.terminate` (`POST /api/v1/targets/<int:pk>/terminate/`) is the AWS call (T1). It must not leave `status=ready` (decommissioned / error). `target.delete` for `kind=aws_ec2` calls `terminate_instance` then deletes the Django row **only if terminate succeeded** (absent == success counts as success). Terminate **failure** files kind `aws-terminate-failed` fingerprint `aws-terminate:{target.pk}` P1 and **does not delete the row** (operator retries T1 terminate). SSH kind is unchanged (row delete only). Every new mutating playbook is run-twice with **zero** mutating Transport / mutating provider calls the second time (D-018).

### C12 — Finding kinds / fingerprints

Register in `monitor/alert_rules.py` **before** first `raise_alert`. Tokens never in title/body/detail. Kind and fingerprint are **different strings** (CF pattern: `cf-token-scope` / `cf-scope:…`). Task lists quote the **fingerprint** column, not the kind.

| kind | sev | fingerprint |
|---|---|---|
| `aws-scope` | p2 | `aws-scope:{account_id}` |
| `aws-create-failed` | p2 | `aws-create:{name}` |
| `aws-terminate-failed` | p1 | `aws-terminate:{target.pk}` |
| `aws-host-key-timeout` | p1 | `aws-host-key-timeout:{name}` |
| `r53-fail` | p2 | `r53-fail:{zone.pk}` |
| `ssm-fail` | p2 | `ssm-fail:{target.pk}` |
| `budget-cap-hit` | p1 (exists) | `budget-cap-hit:aws` |

L5 missing edge stays `attack-playbook-engaged:{zone.pk}` notify-only.

### Already correct (keep)

D-054/D-057/D-059/D-060/D-064. `0009`/`0010`/`0011` closed. `findings` is the canonical topic. Triple key for test-plane DNS. `deploys/` never imports `providers.cloudflare` or boto3. Secrets through the vault. Reversible-by-default. `scaling/attack_gate.py` stays. `ssh.rotate` stays T1. FakeCloudProvider / FakeDnsProvider remain what tests inject. `providers/**` already sensitive-path.

### Sensitive-path additions (Task 0 claims before the first line of code)

`providers/ec2.py` · `providers/route53.py` · `providers/ssm.py` · `providers/image_registry.py` · `providers/aws_creds.py` · `monitor/cloud_reaper.py` · `provision/aws_enroll.py` · **`core/aws_views.py`**. `providers/**`, `core/ssh.py`, `core/test_mode.py`, `core/actions.py`, `monitor/reaper.py`, `monitor/alert_rules.py` already listed. Do not fold AWS connect into unclaimed `core/zone_views.py`. Do not broaden to `deploys/**` or `frontend/**` wholesale — Settings AWS and Targets enroll land in existing claimed / ordinary UI files as the tasks name them.
