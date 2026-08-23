# Phase 5 tasks — AWS adapters (T1 moto)

SDD-ready work list for Implementers. Architect design note:
`docs/phase-5-design-note.md` r2 (panel §7 is binding). Do not start a task
whose dependencies are open. Do not start implementation from the design
session until the design panel records MERGE. Do not invent a path, env,
Finding fingerprint, action id, CheckRun key, or gate shape that the
design note does not name.

**Branch:** cut task branches from `p5-design` (which carries these two docs).
Never implement on `master`. Sensitive-path merges to `master` go through the
recorded expert-panel vote.

## Global constraints (every task)

- Every remote effect on a target goes through `Transport`; argv lists, never
  interpolated strings; file content via `put()`, never heredocs.
- Cloud / DNS / SSM / registry HTTP+SDK lives **only** under `providers/`.
  `deploys/`, `vault/`, `monitor/`, `provision/`, and `tests/` never import
  boto3 / botocore / moto. `deploys/` never constructs a cloud client.
  Ship / provision / reaper take ports from `providers/registry.py`.
- Secrets through the vault. No AWS / DNS / edge / SSM token or parameter
  **value** in a Finding, CheckRun, log, task arg, or `AuditEvent.detail`.
- **Pinned env names:** `HUB_AWS_CREDENTIALS_REF` → `AWS_CREDENTIALS_REF`
  default `""`. `HUB_TEST_AWS_ACCOUNT_IDS`. `HUB_TEST_AWS_REGIONS`.
  `HUB_AWS_HOURLY_BUDGET_USD` → `AWS_HOURLY_BUDGET_USD` default `""`.
  `HUB_TEST_ZONE_SLUGS` stays the DNS/NetworkZone allowlist.
  `HUB_TEST_DNS_ZONE` is retired. **Do not invent `HUB_TEST_CF_TOKEN` or
  `HUB_TEST_AWS_TOKEN` / `HUB_TEST_AWS_ACCESS_KEY_ID`.**
- Product AWS clients take explicit `aws_access_key_id` /
  `aws_secret_access_key` from the vault JSON
  `{access_key_id, secret_access_key}`. Never the default credential chain.
  Empty `AWS_CREDENTIALS_REF` refuses even if a leftover vault row exists.
- Test-plane AWS is quadruple-keyed: `HUB_TEST_MODE` **and**
  `purpose=test` tags **and** account id on `HUB_TEST_AWS_ACCOUNT_IDS` **and**
  region on `HUB_TEST_AWS_REGIONS` (empty list = refuse live). DNS stays
  triple-keyed with `HUB_TEST_ZONE_SLUGS`.
- **`0011` is closed.** The only Hub migration is Task 1's `0012_phase5.py`.
  No `Site.tier`. No `NetworkZone.kind`. No `CloudAccount` table.
- **`findings` is the canonical realtime topic.** Kind ≠ fingerprint.
  Every “files …” line quotes design-note §7 C12 **fingerprint**, not kind.
- Every new mutating playbook is run-twice with **zero** mutating Transport
  / mutating provider calls the second time (§D6, D-018).
- New alert kinds need a row in `monitor/alert_rules.py` first. Kinds and
  fingerprints are design-note §7 C12 only.
- `EdgeProtection` remains Cloudflare-only. Route 53 is DnsProvider only.
  L5 against a Route 53 zone is notify-only, never a silent no-op.
- SSM prefix is `/deploy-hub/{target.pk}/` only (not a slug).
- Do not claim a 24 h Hub-down (D-042). Do not enable live AWS (Joseph
  interrupt). Do not complete Hub-central DNS-01.
- Reviewer never writes the code they review (D-014).
- Tiers: T1 = fakes/moto. T2 = `hub-test-target`. T3 = Multipass. A
  `tier: t2|t3` req is verified only by a passed marked test (D-024).
  **New Phase 5 ids are tier-less.** Do not extend `VALID_TIERS` with `t4`.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the
  round they judge. Registry edits are Task 0.
- `FakeCloudProvider` remains the test default. Tests inject fakes; they do
  not construct product boto3 clients.
- UI copy says Target, never “instance” (D9). NAV stays six items.
- **Markers:** `conformance/check.py::collect_markers` counts only
  **function-level** `@pytest.mark.req("<id>")` on `def test_*`. Module
  `pytestmark` is invisible to that walker (see
  `test_sec_b3_function_decorators_are_visible_to_collect_markers`). Do not
  pin a MUST id only on `pytestmark`. No AWS-* / UX-P5-* / P5-AWS-DEMO
  marker on a skip-unless or live test. No MUST id on a test that does not
  prove that clause.
- TDD: failing test first. Long "why" HEREDOC commits; no amend.

Protective cut (**D-065**): MUST = Tasks 0–9 and 11. Task 10 (SSH-CA
writeup) is the named slip line and does **not** block the MUST demo.
First slip = SSH-CA evaluation (not enablement; dual-key rotate stays).

## Parallel waves

| Shared file | Order |
|---|---|
| `conformance/requirements.yaml` / `Makefile` / `DECISIONS.md` / `WAIVERS.md` / `conformance/paths.yaml` / `.github/CODEOWNERS` | Task 0 |
| `core/models.py` / `0012_phase5.py` | Task 1 after 0 (only writer) |
| `providers/aws_creds.py` / `core/test_mode.py` / `hub/settings/base.py` / `core/aws_views.py` / `core/zone_urls.py` / `frontend/src/screens/Settings.jsx` / `monitor/alert_rules.py` | Task 2 after 0 |
| `providers/ec2.py` / `providers/registry.py` (`cloud_provider_for`) / `providers/fakes.py` (FakeCloudProvider return) | Task 3 after 2 |
| `providers/route53.py` / `providers/registry.py` (dns branch) | Task 4 after **1+2** |
| `provision/aws_enroll.py` / `core/actions.py` (`instance.create`) / `hub/urls.py` (`instance/create/`) / `frontend/src/screens/Targets.jsx` / `frontend/src/Tiers.jsx` | Task 5 after **1+2+3** (hard) |
| `core/views.py` (`TargetDeleteView`) / `core/actions.py` (`instance.terminate`) / `hub/urls.py` (`targets/<pk>/terminate/`) / `monitor/cloud_reaper.py` | Task 6 after 5 |
| `providers/image_registry.py` / `providers/registry.py` (`image_registry_for`) / `deploys/steps.py` (`ensure_ship`) | Task 7 after 2 |
| `providers/ssm.py` / `providers/registry.py` (`ssm_for`) / `deploys/steps.py` (`_put_env_file` call site only) | Task 8 after 2 |
| `monitor/tasks.py` (`audit_aws_iam_scope`) | Task 9 after **1+2** |
| SSH-CA writeup | Task 10 (SLIP) |
| acceptance + demo | Task 11 after MUST |

Independent after Task 2 (parallel worktrees): **Tasks 3, 7, 8 only**.
Task 4 needs `DnsAccount.Provider.ROUTE53`. Task 9 needs
`CheckRun.Kind.AWS_IAM_SCOPE`. Task 5 needs schema + Settings ref + EC2
port — not “prefer.” Task 1 is the schema wave — do not collide with it
on `core/models.py`. Task 5 adds the `instance.create` ACTION_TIERS row;
Task 6 adds `instance.terminate`. If both touch `core/actions.py`, Task 6
waits for Task 5 or only appends the terminate tuple.

---

## Task 0 — Unblock `check.py --phase 5` (D-065…D-074)

**Title:** Phase-5 due set exists; PART-K moved to 5.5; `conformance-5`
excludes live tiers; sensitive paths claimed. Waives nothing that is MUST.

**Files created/touched:**
- `DECISIONS.md` — rows D-065…D-074 (text from the design note §5).
- `conformance/requirements.yaml` (sensitive) — bump `PART-K1-ZERO-INBOUND-HUB`,
  `PART-K2-REPLAY-AT-HUB`, `PART-K6-NO-INTERNAL-ACTIONS` to `phase: 5.5`.
  Leave `text:` / `text_hash:` untouched. Add the ten new ids by **copying**
  design note §3 (`phase: 5`, no `tier:`, `verify: test` except
  `P5-AWS-DEMO` `verify: demo` / `demo: conformance/demos/phase-5.md`,
  one-sentence `text:` as written). Compute `text_hash:` with
  `python conformance/check.py --print-text-hashes`. Do not change
  `text:` / `text_hash:` of any existing id. Do not mark full-text §I
  Phase 5 / §D5 (Azure, SSH-CA enablement, Key Vault, T3 aws) on any test.
- `tests/test_d023_actions_not_required.py` — pin `conformance` to
  `--phase 5 --exclude-tier t2 --exclude-tier t3`. Leave `conformance-3`
  as all-tiers `--phase 3` with **no** `--exclude-tier`. Leave
  `conformance-4` as `--phase 4 --exclude-tier t2 --exclude-tier t3`.
- `WAIVERS.md` — **no new MUST waiver.** Do not retire TLS-B2 / SEC-B2 /
  REL-P2 / LE-staging. Do not waive `failed` / `not-collected`.
- `Makefile` — `conformance` becomes `--phase 5 --exclude-tier t2
  --exclude-tier t3`. Add `conformance-5` as the same recipe. Leave
  `conformance-4` as **phase 4 minus live**. Leave `conformance-3` as
  **all-tiers Phase 3**. Leave `conformance-3.5` unchanged. Add
  `conformance-5` to `.PHONY`. Do **not** add an all-tiers 5 target.
  Do **not** add `t4` to anything. `nightly-gates` still uses
  `conformance-3`.
- `conformance/paths.yaml` + `.github/CODEOWNERS` — claim the
  sensitive-path additions in the design note (files that do not exist
  yet are listed): `providers/ec2.py`, `providers/route53.py`,
  `providers/ssm.py`, `providers/image_registry.py`,
  `providers/aws_creds.py`, `monitor/cloud_reaper.py`,
  `provision/aws_enroll.py`, **`core/aws_views.py`**.
- `docs/phase-5-design-note.md` / this file — already on the branch.

**Exact req ids proven:** none go green here except the gate shape. This
task makes the phase-5 due set honest. Do not create
`conformance/demos/phase-5.md` (a non-empty stub would verify
`P5-AWS-DEMO`).

**Tests to write** (function-level `@pytest.mark.req` is N/A — no MUST id
greens here):
- `tests/test_conformance_gate.py` (extend) —
  `test_phase_5_due_set_includes_all_ten_section_3_ids` asserts the live
  registry contains all ten §3 ids at `phase: 5` with **no `tier:` key**:
  `AWS-EC2-ADAPTER`, `AWS-R53-ADAPTER`, `AWS-ENROLL-PIN`,
  `AWS-TEST-PLANE`, `AWS-IAM-ALLOWLIST`, `AWS-SSM-PULL`,
  `AWS-IMAGE-REGISTRY`, `AWS-INSTANCE-T1`, `UX-P5-AWS-OPERATOR`
  (`verify: test`) and `P5-AWS-DEMO` (`verify: demo`, names
  `conformance/demos/phase-5.md`);
  `test_part_k_ids_are_phase_5_5_not_5`;
  `test_new_phase_5_ids_have_no_tier`;
  `test_p5_aws_demo_names_phase_5_md`;
  `test_tls_b2_hub_dns01_stays_phase_4`;
  `test_valid_tiers_still_t1_t2_t3_only`;
  `test_no_all_tiers_5_target` (assert the Makefile target does **not**
  exist).
- `tests/test_makefile_nightly.py` — **rewrite**
  `test_review_round_conformance_is_phase_4_minus_live_tiers` so it cannot
  remain as a `--phase 4` pin on `conformance`. Replacement:
  `test_review_round_conformance_is_phase_5_minus_live_tiers`. Keep
  `test_nightly_gates_use_conformance_3` unchanged (all-tiers Phase 3).
  Keep `test_conformance_4_is_phase_4_minus_live_tiers` unchanged
  (`conformance-4` stays). Also:
  `test_conformance_5_target_exists`;
  `test_conformance_5_is_phase_5_minus_live_tiers`;
  `test_conformance_4_still_phase_4_minus_live_tiers`;
  `test_conformance_3_still_all_tiers_phase_3`;
  `test_conformance_5_is_not_a_nightly_gates_prereq`.
  Do not add a test that claims `conformance-3` excludes live tiers.

**Dependencies:** none.

---

## Task 1 — Schema wave `0012_phase5.py`

**Title:** `Target.Kind.AWS_EC2` + nullable `provider_ref` + every CheckRun
kind this phase needs. `0011` stays closed.

**Files:** `core/models.py` (**this task is the only writer this phase**),
`core/migrations/0012_phase5.py`, `tests/test_target_aws_kind.py` (or
extend existing model tests).

**Do:**
- `Target.Kind.AWS_EC2 = "aws_ec2"`.
- `Target.provider_ref = CharField(max_length=64, null=True, blank=True)`
  (instance id). SSH rows stay null. Do not overload `host`.
- Python-only `DnsAccount.Provider.ROUTE53 = "route53"`. If
  makemigrations emits AlterField on `DnsAccount.provider`, fold it into
  `0012`. No new table.
- Python-only Kind values: `aws_iam_scope`, `aws_reaper`.
- Do **not** add `NetworkZone.kind`, `Site.tier`, `Site.secrets_mode`,
  or a `CloudAccount` table. `Secret.Kind.CLOUD_CREDENTIAL` already exists.
- Later tasks do **not** edit `core/models.py`.

**Exact req ids proven:** none (schema enables later markers; do not hang
an AWS-* id on a model-choice test).

**Tests:**
- `test_target_kind_aws_ec2_exists`
- `test_provider_ref_nullable_on_ssh_target`
- `test_provider_ref_max_length_64`
- `test_dnsaccount_provider_route53_exists`
- `test_checkrun_kinds_aws_iam_scope_and_aws_reaper_exist`
- `test_no_networkzone_kind_and_no_site_tier`
- existing seed `burst-ec2-1` kind is now a legal choice (no model clean
  error)

**Dependencies:** Task 0.

---

## Task 2 — AWS credentials, IAM construction refuse, Settings tab, test-plane wall

**Title:** Vault-ref explicit keys; never default chain; IAM allowlist at
construction (user **and** groups); Settings AWS tab; named allowlists;
register C12 kinds.

**Files:** `providers/aws_creds.py` (new; boto3 allowed),
`providers/registry.py` (loader helpers only — not `cloud_provider_for`
yet), `core/test_mode.py` (`assert_test_aws`),
`hub/settings/base.py` (`HUB_AWS_CREDENTIALS_REF` → `AWS_CREDENTIALS_REF=""`,
`HUB_TEST_AWS_ACCOUNT_IDS`, `HUB_TEST_AWS_REGIONS`,
`HUB_AWS_HOURLY_BUDGET_USD` → `AWS_HOURLY_BUDGET_USD=""`),
`hub/settings/prod.py` (do not default the ref or allowlists on),
`core/aws_views.py` (new; `POST /api/v1/aws/connect/` — do **not** put
this on `core/urls.py`, which is `/api/auth/`),
`core/zone_urls.py` (include `aws/connect/`),
`frontend/src/screens/Settings.jsx` (AWS tab peer of Cloudflare),
`frontend/tests/settings-aws.test.ts`,
`monitor/alert_rules.py` (register every C12 kind that does not already
exist; do not raise them yet except construction `aws-scope`),
`requirements.txt` (pin `boto3`; botocore transitive),
`tests/test_aws_creds.py` (**must not import boto3/moto**).

**Do:**
- Load `Secret.Kind.CLOUD_CREDENTIAL` / `owner_type="aws"` /
  `owner_id=AWS_CREDENTIALS_REF`. JSON keys exactly
  `{access_key_id, secret_access_key}`. Extra keys / session token refuse.
- Pass explicit keys into any boto3 client this helper builds. A
  constructor that omits them is a failing test even inside moto
  (inspect `boto3.client(...)` kwargs: both keys present,
  `aws_session_token` not taken from env).
- Empty ref refuses. Do not scan the vault for leftover rows.
- `assert_test_aws(account_id, region)`: under `HUB_TEST_MODE` both
  allowlists must contain the values; empty allowlist refuses. Outside
  it, `purpose=test` tagged calls refuse.
- IAM helper inspects user attached+inline **and** `ListGroupsForUser` +
  each group's attached+inline, plus a present permission boundary.
  Missing user inspect **or** missing group inspect = refuse. Refuse `*`
  / `AdministratorAccess` / `NotAction` / Hub-user `ec2:*` / `ssm:*` /
  `iam:*` / `iam:CreateAccessKey` / `iam:AttachUserPolicy` /
  `iam:PutUserPolicy` / `iam:PassRole` on `*` / `sts:AssumeRole` /
  off-prefix SSM / off-zone Route 53. File kind `aws-scope` fingerprint
  `aws-scope:{account_id}` with refs, never secrets.
- Settings AWS tab: unconfigured (`AWS_CREDENTIALS_REF==""`) = degraded
  “not connected”, never “Connected”. Paste is write-only. Observe
  GetCallerIdentity + allowlist **before** `vault.put`. Put under
  `owner_id=settings.AWS_CREDENTIALS_REF`. Empty setting → connect
  400/409 with the degraded reason. 201 never echoes keys.
- Do not add a 7th NAV item. Do not add `connect_aws` to
  `core/checklist.py` `ITEM_IDS`.
- T1 observe uses dummy creds inside a provider helper (or Fake policy
  document). `tests/` import the helper, not boto3.
- Pin boto3 in `requirements.txt`. moto stays `requirements-dev`. No
  LocalStack.

**Exact req ids:** `AWS-TEST-PLANE`, `AWS-IAM-ALLOWLIST`. Function-level
`@pytest.mark.req` on the named tests below. Do **not** mark
`UX-P5-AWS-OPERATOR` here (F8/cost land in Task 5). No live / skip-unless
marker on these ids.

**Tests:**
- `test_empty_aws_credentials_ref_refuses` — `AWS-TEST-PLANE`
- `test_explicit_keys_passed_into_client_never_default_chain` — `AWS-TEST-PLANE`
- `test_session_token_or_extra_json_keys_refused` — `AWS-TEST-PLANE`
- `test_empty_allowlist_refuses_live` — `AWS-TEST-PLANE`
- `test_off_allowlist_account_or_region_refuses_under_hub_test_mode` — `AWS-TEST-PLANE`
- `test_purpose_test_refuses_outside_hub_test_mode` — `AWS-TEST-PLANE`
- `test_connect_without_ref_does_not_invent_a_token_env` — `AWS-TEST-PLANE`
- `test_star_action_refuses_and_files_aws_scope` — `AWS-IAM-ALLOWLIST`
- `test_administrator_access_refuses` — `AWS-IAM-ALLOWLIST`
- `test_group_attached_administrator_access_refuses` — `AWS-IAM-ALLOWLIST`
- `test_missing_iam_inspect_refuses` — `AWS-IAM-ALLOWLIST`
- `test_missing_group_inspect_refuses` — `AWS-IAM-ALLOWLIST`
- `test_not_action_refuses` — `AWS-IAM-ALLOWLIST`
- `test_ec2_star_or_ssm_star_refuses` — `AWS-IAM-ALLOWLIST`
- `test_escalation_verbs_refuse` — `AWS-IAM-ALLOWLIST`
- `test_off_prefix_ssm_refuses` — `AWS-IAM-ALLOWLIST`
- `test_off_zone_route53_refuses` — `AWS-IAM-ALLOWLIST`
- `test_finding_body_has_refs_never_secret` — `AWS-IAM-ALLOWLIST`
- `test_finding_fingerprint_is_aws_scope_account_id` — `AWS-IAM-ALLOWLIST`
- `test_settings_unconfigured_is_degraded_not_connected` (unmarked; UX id waits for Task 5)
- `test_connect_observes_before_vault_write`
- `test_connect_201_never_echoes_keys`
- `test_aws_creds_tests_do_not_import_boto3`
- `test_nav_still_six`
- `test_checklist_has_no_connect_aws`
- frontend: AWS tab exists; paste write-only; degraded empty/error
- **no live AWS test**

**Dependencies:** Task 0. Do not edit `core/models.py`.

---

## Task 3 — EC2 adapter + `cloud_provider_for` + Fake return shape

**Title:** `providers/ec2.py` implements CloudProvider; moto helper in-module;
`cloud_provider_for` is the only constructor; IMDSv2 + hop-limit 1; 22 not
public; `ensure_ingress_rules` refuses public 22; no `CreateKeyPair`.

**Files:** `providers/ec2.py` (new; `mock_aws_ec2`), `providers/registry.py`
(`cloud_provider_for`), `providers/fakes.py` (`FakeCloudProvider.create_instance`
returns `{id, state, public_ip, host_key_fingerprint}` and keeps
idempotent terminate), `providers/base.py` (docstring only if the return
contract needs a line), `tests/test_ec2_provider.py` (**no boto3/moto
import**), extend `tests/test_smoke.py` / `tests/test_import_rule.py` as
needed.

**Do:**
- Implement `create_instance`, `get_instance`, `terminate_instance`
  (absent == success, including moto-missing-id), `ensure_ingress_rules`,
  `list_tagged_instances`, `create_image` (T1 fake id; AMIs are not a
  secret store), `estimate_hourly_cost` (in-module table, not Price List).
- `RunInstances` kwargs include `HttpTokens=required` and
  `HttpPutResponseHopLimit=1`. Default SG has no 22/tcp `0.0.0.0/0` or
  `::/0`. `ensure_ingress_rules` refuses 22/tcp (and ssh) from
  `0.0.0.0/0` and `::/0`.
- Under `HUB_TEST_MODE`, spec without `tags.purpose=test` refuses.
- Host keys from `GetConsoleOutput` (Fake: immediate fingerprint).
  Timeout → raise, never TOFU. Fingerprint matches
  `paramiko.PKey.fingerprint` equality.
- Accept a caller-supplied **public** key (UserData
  `ssh_authorized_keys` or `ImportKeyPair`). Never `CreateKeyPair`.
  Never Hub `CLOUD_CREDENTIAL` / private key / SSM values in UserData.
- `cloud_provider_for` loads via Task 2's helper, fail-closed, returns
  the EC2 adapter. Tests inject `FakeCloudProvider` and never need this
  constructor for pipeline defaults.
- Dummy static creds inside `mock_aws_ec2` (copy `mock_aws_kms`).

**Exact req ids:** `AWS-EC2-ADAPTER`. Function-level `@pytest.mark.req`
on the named tests below. No live / skip-unless marker.

**Tests:**
- `test_cloud_provider_for_is_the_only_constructor` — `AWS-EC2-ADAPTER`
- `test_create_instance_returns_host_key_fingerprint` — `AWS-EC2-ADAPTER`
- `test_runinstances_requires_imdsv2_and_hop_limit_1` — `AWS-EC2-ADAPTER`
- `test_default_sg_has_no_public_22` — `AWS-EC2-ADAPTER`
- `test_ensure_ingress_rules_refuses_public_22_ipv4_and_ipv6` — `AWS-EC2-ADAPTER`
- `test_purpose_test_required_under_hub_test_mode` — `AWS-EC2-ADAPTER`
- `test_terminate_absent_is_success` — `AWS-EC2-ADAPTER`
- `test_host_key_timeout_refuses_not_tofu` — `AWS-EC2-ADAPTER`
- `test_create_keypair_not_used` — `AWS-EC2-ADAPTER`
- `test_no_hub_cloud_credential_in_userdata` — `AWS-EC2-ADAPTER`
- `test_estimate_hourly_cost_fake_is_0_05` — `AWS-EC2-ADAPTER`
- `test_create_image_returns_id_and_is_not_a_secret_store` — `AWS-EC2-ADAPTER`
- `test_fake_cloud_create_still_has_id_and_idempotent_terminate`
- `test_ec2_tests_do_not_import_boto3`
- `test_deploys_vault_monitor_tests_still_do_not_import_boto3`
- **no live AWS test**

**Dependencies:** Task 0 + Task 2.

---

## Task 4 — Route 53 DnsProvider

**Title:** `providers/route53.py` implements DnsProvider only; proxied=True
raises; L5 notify-only; fail-closed `dns_provider_for` branch.

**Files:** `providers/route53.py` (new; `mock_aws_route53`),
`providers/registry.py` (Route 53 branch of `dns_provider_for` only),
`tests/test_route53_provider.py` (**no boto3/moto import**),
`tests/test_attack_playbook.py` (extend: Route 53 zone → notify-only).

**Do:**
- `capabilities()` omits `proxied`. `upsert_record(..., proxied=True)`
  raises. Do not silently write an unproxied A.
- Class is not an `EdgeProtection`. `edge_protection_for` still raises on
  a non-cloudflare provider **with** an edge ref, and returns None when
  the ref is absent.
- Construction: CLOUD_CREDENTIAL via `AWS_CREDENTIALS_REF`;
  `DnsAccount.dns_token_ref` holds that same owner-id. Refuse if
  `dns_token_ref != AWS_CREDENTIALS_REF`. Never copy CLOUD_CREDENTIAL
  into an `API_TOKEN` row. Purpose wall uses `HUB_TEST_ZONE_SLUGS` for
  zone names. Changes only on that `DnsZone.provider_zone_id`.
- Public proxied sites stay Cloudflare. Do not pull DNS-01 into this
  task.
- File kind `r53-fail` fingerprint `r53-fail:{zone.pk}` on provider
  errors (refs, not tokens).

**Exact req ids:** `AWS-R53-ADAPTER`. Function-level `@pytest.mark.req`
on the named tests below. No live / skip-unless marker.

**Tests:**
- `test_route53_is_not_edge_protection` — `AWS-R53-ADAPTER`
- `test_upsert_proxied_true_raises` — `AWS-R53-ADAPTER`
- `test_capabilities_omit_proxied` — `AWS-R53-ADAPTER`
- `test_dns_provider_for_route53_fail_closed` — `AWS-R53-ADAPTER`
- `test_dns_provider_for_unknown_provider_still_refuses` — `AWS-R53-ADAPTER`
- `test_l5_against_route53_zone_is_notify_only` — `AWS-R53-ADAPTER`
- `test_edge_ref_on_route53_account_raises` — `AWS-R53-ADAPTER`
- `test_route53_never_loads_edge_token_ref` — `AWS-R53-ADAPTER`
- `test_dns_token_ref_must_equal_aws_credentials_ref` — `AWS-R53-ADAPTER`
- `test_changes_are_scoped_to_provider_zone_id` — `AWS-R53-ADAPTER`
- `test_route53_tests_do_not_import_boto3`
- existing Cloudflare `proxied=True` FakeDnsProvider tests stay green

**Dependencies:** Task 0 + Task 1 + Task 2. Do not edit `core/models.py`
(Provider.ROUTE53 is Task 1).

---

## Task 5 — Enroll: create → pin → provision + T1 + cost overlay + F8

**Title:** `instance.create` T1; Hub-minted public-only SSH; pin before
Transport; `T1Overlay.cost` required; enroll-empty/error/degraded.

**Files:** `provision/aws_enroll.py` (new), `core/actions.py`
(`instance.create` T1, label “Create target”),
`hub/urls.py` (`POST /api/v1/instance/create/` — **not** `core/urls.py`),
enroll view next to that route, `frontend/src/screens/Targets.jsx`,
`frontend/src/Tiers.jsx` (`T1Overlay` takes **required** `cost` on create;
other T1 ids omit it), `frontend/src/actions.js` (no presentation rule
change; T1 already `stepUp: "required"`), `frontend/tests/actions.test.ts`,
`frontend/tests/simulation-states.test.ts` (`enroll-empty`, `enroll-error`,
`enroll-degraded`), `simulation/seed_v1.json` (add a test-purpose
`aws-use1` zone **or** retarget `burst-ec2-1` at an existing zone so the
fixture loads), `tests/test_aws_enroll.py`.

**Do:**
- Playbook: mint per-target Ed25519 in-Hub → `vault.put` `SSH_PRIVATE_KEY`
  → set `ssh_key_ref` → `estimate_hourly_cost` → overlay shows it as
  `T1Overlay.cost` → T1 touch + type-the-name (`confirm_name` = intended
  host) → `create_instance` with **public key only** → write
  `Target.kind=aws_ec2`, `provider_ref`, `host` = Transport address
  (tailnet / Hub-egress, never world-open 22), `host_key_fingerprint`,
  `ssh_key_ref` → **then** `provision_host` over Transport.
- Empty / missing fingerprint refuses before Transport. Timeout waiting
  for keys files kind `aws-host-key-timeout` fingerprint
  `aws-host-key-timeout:{name}` P1 and does not TOFU.
- Create failure files kind `aws-create-failed` fingerprint
  `aws-create:{name}` (C12 — do **not** use the kind as the fingerprint).
  Cap exceeded files existing `budget-cap-hit` fingerprint
  `budget-cap-hit:aws` and refuses. Unconfigured/error estimate refuses
  — never `$0` as free.
- Targets empty state: one sentence + one button. No AWS ref → copy the
  provision CLI. Ref set → Create target. Copy never says “instance”.
- Do not add a 7th NAV item. Do not add a 4th F6 phone screen (overlay
  is already in `PHONE_SCOPE`).
- Run-twice: second pass zero mutating provider / Transport calls.

**Exact req ids:** `AWS-ENROLL-PIN`, `AWS-INSTANCE-T1`,
`UX-P5-AWS-OPERATOR`. Function-level `@pytest.mark.req` on the named
tests below. No live / skip-unless marker.

**Tests:**
- `test_instance_create_is_t1` — `AWS-INSTANCE-T1`
- `test_instance_create_refuses_without_recent_touch` — `AWS-INSTANCE-T1`
- `test_instance_create_requires_type_the_name` — `AWS-INSTANCE-T1`
- `test_totp_does_not_satisfy_instance_create` — `AWS-INSTANCE-T1`
- `test_pin_happens_before_any_transport` — `AWS-ENROLL-PIN`
- `test_empty_pin_still_refuses_transport` — `AWS-ENROLL-PIN`
- `test_host_key_timeout_does_not_tofu` — `AWS-ENROLL-PIN`
- `test_enroll_sets_ssh_key_ref_before_transport` — `AWS-ENROLL-PIN`
- `test_userdata_or_keypair_is_public_key_only` — `AWS-ENROLL-PIN`
- `test_kind_aws_ec2_and_provider_ref_and_host_written` — `AWS-ENROLL-PIN`
- `test_create_finding_fingerprint_is_aws_create_name` — `AWS-ENROLL-PIN`
- `test_cost_visible_on_overlay_before_confirm` — `UX-P5-AWS-OPERATOR`
- `test_unconfigured_estimate_refuses_create` — `UX-P5-AWS-OPERATOR`
- `test_budget_cap_hit_files_existing_kind`
- `test_enroll_run_twice_zero_mutating_calls` — `AWS-ENROLL-PIN`
- frontend: enroll-empty / enroll-error / enroll-degraded render on
  product screens; overlay shows `$0.05/h` (or the Fake number) in words;
  Settings degraded when ref empty; NAV six; copy “Create target” never
  `instance` — `UX-P5-AWS-OPERATOR`

**Dependencies:** Task 0 + Task 1 + Task 2 + Task 3 (hard).

---

## Task 6 — Terminate, delete-terminates, cloud reaper

**Title:** `instance.terminate` T1; `target.delete` on `aws_ec2`
terminates then deletes **on success**; terminate failure keeps the row;
cloud reaper on the CloudProvider port writes `AWS_REAPER`; Multipass
reaper untouched.

**Files:** `core/actions.py` (`instance.terminate` T1, label “Terminate
target”), `core/views.py` (`TargetDeleteView` — terminate then delete
when `kind=aws_ec2` **only if terminate succeeded**; absent == success),
`hub/urls.py` (`POST /api/v1/targets/<int:pk>/terminate/` beside delete
— **not** `core/urls.py`), `monitor/cloud_reaper.py` (new; **no boto3**),
`monitor/drills.py` (weekly FakeCloudProvider `purpose=test` plant +
assert gone + persist `CheckRun.Kind.AWS_REAPER`; do not claim
`HARNESS-REAPER-TEST-PLANE` covers AWS), `monitor/reaper.py`
(**do not add boto3; prefix `hub-t3-` stays**),
`tests/test_aws_terminate.py`, `tests/test_cloud_reaper.py`.

**Do:**
- `instance.terminate` is T1 (touch + type-the-name). It is the AWS
  call. It must not leave `status=ready`.
- `target.delete` stays T1. For `kind=aws_ec2`, call
  `cloud_provider_for(...).terminate_instance(provider_ref)` (or the
  injected port in tests) then delete the Django row **only if terminate
  succeeded**. Already-absent == success. Terminate **failure** files
  kind `aws-terminate-failed` fingerprint `aws-terminate:{target.pk}`
  (C12 — do **not** use the kind as the fingerprint) P1 and **does not
  delete the row**. SSH kind is unchanged (row delete only).
- Cloud reaper: after D-066 wall, `list_tagged_instances({purpose: test})`
  then `terminate_instance`. No-op when `HUB_TEST_MODE` is False. Weekly
  drill plants Fake `purpose=test`, asserts gone, writes
  `CheckRun.Kind.AWS_REAPER`.
- Run-twice zero mutating calls.

**Exact req ids:** `AWS-INSTANCE-T1`, `AWS-TEST-PLANE` (reaper wall).
Function-level `@pytest.mark.req` on the named tests below. No live /
skip-unless marker.

**Tests:**
- `test_instance_terminate_is_t1` — `AWS-INSTANCE-T1`
- `test_instance_terminate_refuses_without_recent_touch` — `AWS-INSTANCE-T1`
- `test_instance_terminate_requires_type_the_name` — `AWS-INSTANCE-T1`
- `test_totp_does_not_satisfy_instance_terminate` — `AWS-INSTANCE-T1`
- `test_terminate_run_twice_zero_mutating_calls` — `AWS-INSTANCE-T1`
- `test_target_delete_on_aws_ec2_terminates_then_deletes` — `AWS-INSTANCE-T1`
- `test_target_delete_on_ssh_does_not_call_terminate` — `AWS-INSTANCE-T1`
- `test_terminate_absent_is_success` — `AWS-INSTANCE-T1`
- `test_terminate_failure_does_not_delete_row` — `AWS-INSTANCE-T1`
- `test_instance_terminate_does_not_leave_ready_target` — `AWS-INSTANCE-T1`
- `test_terminate_finding_fingerprint_is_aws_terminate_target_pk` — `AWS-INSTANCE-T1`
- `test_cloud_reaper_respects_allowlist_and_purpose_test` — `AWS-TEST-PLANE`
- `test_cloud_reaper_noop_when_hub_test_mode_false` — `AWS-TEST-PLANE`
- `test_cloud_reaper_writes_checkrun_kind_aws_reaper` — `AWS-TEST-PLANE`
- `test_cloud_reaper_does_not_import_boto3`
- `test_multipass_reaper_unchanged_no_boto3`
- `test_weekly_drill_plants_fake_purpose_test_and_asserts_gone` — `AWS-TEST-PLANE`
- `test_harness_reaper_test_plane_is_not_claimed_for_aws`

**Dependencies:** Task 5 (enroll writes `kind` / `provider_ref`; append
the ACTION_TIERS tuple after Task 5 if both touch `core/actions.py`).

---

## Task 7 — ImageRegistry port + `ensure_ship` flip

**Title:** `ImageRegistry` + `image_registry_for`; docker load remains
default; Fake TLS+auth with split push/pull creds.

**Files:** `providers/base.py` (`ImageRegistry` port),
`providers/image_registry.py` (new; T1 Fake; ECR boto3 only here if a
real class lands — live ECR is Joseph / skip-unless, unmarked on MUST
ids), `providers/registry.py` (`image_registry_for`),
`providers/fakes.py` (`FakeImageRegistry`), `deploys/steps.py`
(`ensure_ship` takes `desired["registry"]` or None),
`tests/test_image_registry.py` (**no boto3/moto import**).

**Do:**
- Port: `push(tag, archive)`, `pull_spec(tag, *, target) -> {url,
  username, password}` pull-only per-target, `capabilities() >= {tls,
  auth}`.
- `ensure_ship`: `registry is None` → today’s `docker load`. Else push
  then target pull with pull-only cred. Default remains load
  (`ship_mode: load | registry`, default load — desired/manifest, no
  Site column, no 7th NAV).
- Fake requires TLS + auth. Push cred ≠ pull cred. A push-open Fake is
  a failing test.
- Pull login via 0600 cred file or stdin, never password-on-argv.
- `image_registry_for` fail-closed like `dns_provider_for`. Unconfigured
  → None (docker load), not a constructed open registry.
- Do not put boto3 in `providers/registry.py`.

**Exact req ids:** `AWS-IMAGE-REGISTRY`. Function-level `@pytest.mark.req`
on the named tests below. No live / skip-unless marker on this MUST id.

**Tests:**
- `test_ensure_ship_none_still_docker_loads` — `AWS-IMAGE-REGISTRY`
- `test_ensure_ship_with_registry_pushes_and_pulls` — `AWS-IMAGE-REGISTRY`
- `test_fake_registry_requires_tls_and_auth` — `AWS-IMAGE-REGISTRY`
- `test_push_cred_is_not_pull_cred` — `AWS-IMAGE-REGISTRY`
- `test_pull_cred_is_per_target` — `AWS-IMAGE-REGISTRY`
- `test_image_registry_for_unconfigured_returns_none` — `AWS-IMAGE-REGISTRY`
- `test_image_registry_not_in_providers_registry_module_as_ecr_client` — `AWS-IMAGE-REGISTRY`
- `test_nav_still_six`
- `test_image_registry_tests_do_not_import_boto3`
- `test_ensure_ship_run_twice_zero_mutating_calls` — `AWS-IMAGE-REGISTRY`

**Dependencies:** Task 0 + Task 2. Do not edit `core/models.py`.

---

## Task 8 — SSM pull seam

**Title:** `providers/ssm.py` T1 fake; push stays default; instance
profile Get-only on `/deploy-hub/{target.pk}/*`; never static AWS keys
on a target.

**Files:** `providers/ssm.py` (new; `mock_aws_ssm`),
`providers/registry.py` (`ssm_for(target)`), `providers/fakes.py`
(`FakeSsm`), `deploys/steps.py` (branch in `_put_env_file` / caller:
`desired["secrets_mode"] == "ssm_pull"`), `tests/test_ssm.py`
(**no boto3/moto import**), extend `tests/test_no_token_exfiltration.py`.

**Do:**
- Paths `/deploy-hub/{target.pk}/…` **only** (not a slug). Hub SSM
  Put/Get/Delete/AddTags on `/deploy-hub/*` only. Instance profile
  Get-only on `/deploy-hub/{target.pk}/*` — no Put, no `ec2:*`, no
  `iam:*`.
- Default `secrets_mode` is `push` (`_put_env_file` unchanged). Flip is
  desired/manifest, **not** `Site.tier`.
- Pull never writes `AWS_ACCESS_KEY_ID` / Hub IAM user keys / parameter
  values onto the target env file. File kind `ssm-fail` fingerprint
  `ssm-fail:{target.pk}` on error (refs, not values).
- `ssm_for` fail-closed via Task 2's loader.

**Exact req ids:** `AWS-SSM-PULL`. Function-level `@pytest.mark.req` on
the named tests below. No live / skip-unless marker.

**Tests:**
- `test_push_remains_default` — `AWS-SSM-PULL`
- `test_ssm_pull_uses_prefix_deploy_hub_target_pk` — `AWS-SSM-PULL`
- `test_instance_profile_policy_is_get_only` — `AWS-SSM-PULL`
- `test_no_aws_access_key_id_on_target` — `AWS-SSM-PULL`
- `test_no_ssm_value_in_finding_checkrun_log_task_arg_detail` — `AWS-SSM-PULL`
- `test_off_prefix_put_refuses` — `AWS-SSM-PULL`
- `test_secrets_mode_is_not_site_tier` — `AWS-SSM-PULL`
- `test_ssm_tests_do_not_import_boto3`
- `test_ssm_run_twice_zero_mutating_calls` — `AWS-SSM-PULL`

**Dependencies:** Task 0 + Task 2. Do not edit `core/models.py`. If Task 7
is in flight on `deploys/steps.py`, take it as parent or touch only the
env-file helper.

---

## Task 9 — IAM daily audit Beat

**Title:** Daily allowlist audit; same refuse as construction (user **and**
groups); CheckRun `aws_iam_scope`.

**Files:** `monitor/tasks.py` (`audit_aws_iam_scope` — CF
`audit_cf_token_scope` shape), `hub/settings/base.py` Beat
`aws-iam-scope-daily` → `monitor.tasks.audit_aws_iam_scope`,
`tests/test_aws_iam_audit.py` (**no boto3/moto import**).

**Do:**
- Beat loads the Hub user's attached/inline **and** group
  attached/inline policies through the Task 2 helper and refuses the
  same superset (including `NotAction`, service-star, escalation verbs,
  missing group inspect). Drift files kind `aws-scope` fingerprint
  `aws-scope:{account_id}` P2. Clean run is SUCCEEDED with refs, never
  secrets, in `CheckRun.results` (`kind=aws_iam_scope`).
- Absent `AWS_CREDENTIALS_REF` → SKIPPED, not a T1-sibling green of a
  live id (there is no live MUST id).
- Do not mark a live-AWS req.

**Exact req ids:** `AWS-IAM-ALLOWLIST`. Function-level `@pytest.mark.req`
on the named tests below. No live / skip-unless marker on this MUST id
(the skip-absent-ref test stays **unmarked**).

**Tests:**
- `test_daily_audit_refuses_star` — `AWS-IAM-ALLOWLIST`
- `test_daily_audit_refuses_administrator_access` — `AWS-IAM-ALLOWLIST`
- `test_daily_audit_refuses_group_attached_admin` — `AWS-IAM-ALLOWLIST`
- `test_daily_audit_files_aws_scope_on_drift` — `AWS-IAM-ALLOWLIST`
- `test_absent_ref_skips_and_does_not_green_live_aws` (**unmarked**)
- `test_results_have_refs_never_secret` — `AWS-IAM-ALLOWLIST`
- `test_aws_iam_audit_tests_do_not_import_boto3`

**Dependencies:** Task 0 + Task 1 + Task 2. Do not edit `core/models.py`
(`Kind.AWS_IAM_SCOPE` is Task 1).

---

## Task 10 — SLIP: SSH-CA evaluation writeup (does not block MUST demo)

**Title:** Written evaluation only. Dual-key rotate stays (D-064 / D-070).
Not enablement. Hub-held CA private key would mint any host cert.

**Files:** `docs/ssh-ca-evaluation.md` (same shape as
`docs/tailnet-lock-evaluation.md` / `docs/yubikey-kek-rung-2-evaluation.md`).

**Do:**
- Evaluate SSH-CA vs dual-key rotate (§B7 / §J2). Decide **not** to
  enable this phase. Record what would reverse it (D-064's reverse
  condition is SSH-CA landing later, not this writeup).
- Do not add a CA key to the vault. Do not change `provision/ssh_rotate.py`.
- Do not register a phase-5 due id that this writeup would have to mark.
- MUST demo does not wait.

**Exact req ids:** none.

**Tests:** none required. Existing dual-key rotate tests stay green.

**Dependencies:** none for the writeup. MUST demo does not wait.

---

## Task 11 — Acceptance + demo

**Title:** `tests/acceptance/test_phase_5.py` + `conformance/demos/phase-5.md`

**Files:** those two. `@pytest.mark.acceptance(phase=5)` on the module
(acceptance mark, not a MUST `@pytest.mark.req`). Demo record is
non-empty and names the MUST path in design note §4. Do not claim live
AWS. Do not claim SSH-CA enablement. Do not claim DNS-01.

**Exact req ids:** `P5-AWS-DEMO` (`verify: demo` — the file, not a
pytest marker).

**Named acceptance nodeids** (one per §4 beat; `tests/acceptance/test_phase_5.py::`):
- `test_empty_ref_paints_degraded_not_connected`
- `test_connect_observes_before_vault_put`
- `test_connect_201_never_echoes_keys`
- `test_iam_refuse_files_aws_scope`
- `test_t1_create_shows_cost_fake_0_05`
- `test_enroll_public_key_only_ssh_key_ref_before_transport`
- `test_pin_before_transport`
- `test_empty_pin_refuses_transport`
- `test_target_delete_terminates_then_deletes`
- `test_terminate_failure_does_not_delete_row`
- `test_instance_terminate_is_t1`
- `test_route53_fail_closed_proxied_raises_l5_notify_only`
- `test_ensure_ship_none_docker_loads`
- `test_fake_registry_tls_auth_split_creds`
- `test_ssm_get_only_no_target_keys`
- `test_cloud_reaper_vs_multipass`
- `test_empty_allowlist_ref_and_default_chain_refuse`
- `test_nav_stays_six`

Pin a `NAMED` tuple of those function names in the acceptance module
(phase-4 shape). `VALID_TIERS` stays `{t1, t2, t3}`.

**Dependencies:** Tasks 1–9 (not 10).
