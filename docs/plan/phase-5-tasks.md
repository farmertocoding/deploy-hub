# Phase 5 tasks — AWS adapters (T1 moto)

SDD-ready work list for Implementers. Architect design note:
`docs/phase-5-design-note.md` (panel §7 is binding). Do not start a task whose
dependencies are open. Do not start implementation from the design session
until the design panel records MERGE. Do not invent a path, env, Finding
fingerprint, action id, CheckRun key, or gate shape that the design note
does not name.

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
- **`findings` is the canonical realtime topic.**
- Every new mutating playbook is run-twice with **zero** mutating Transport
  / mutating provider calls the second time (§D6, D-018).
- New alert kinds need a row in `monitor/alert_rules.py` first. Kinds and
  fingerprints are design-note §7 C12 only.
- `EdgeProtection` remains Cloudflare-only. Route 53 is DnsProvider only.
  L5 against a Route 53 zone is notify-only, never a silent no-op.
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
- TDD: failing test first. Long "why" HEREDOC commits; no amend.

Protective cut (**D-065**): MUST = Tasks 0–9 and 11. Task 10 (SSH-CA
writeup) is the named slip line and does **not** block the MUST demo.
First slip = SSH-CA evaluation (not enablement; dual-key rotate stays).

## Parallel waves

| Shared file | Order |
|---|---|
| `conformance/requirements.yaml` / `Makefile` / `DECISIONS.md` / `WAIVERS.md` / `conformance/paths.yaml` / `.github/CODEOWNERS` | Task 0 |
| `core/models.py` / `0012_phase5.py` | Task 1 after 0 (only writer) |
| `providers/aws_creds.py` / `core/test_mode.py` / `hub/settings/base.py` / `frontend/src/screens/Settings.jsx` / `monitor/alert_rules.py` | Task 2 after 0 |
| `providers/ec2.py` / `providers/registry.py` (`cloud_provider_for`) / `providers/fakes.py` (FakeCloudProvider return) | Task 3 after 2 |
| `providers/route53.py` / `providers/registry.py` (dns branch) | Task 4 after 2 |
| `provision/aws_enroll.py` / `core/actions.py` (`instance.create`) / `frontend/src/screens/Targets.jsx` / `frontend/src/Tiers.jsx` | Task 5 after 1 + 3 |
| `core/views.py` (`TargetDeleteView`) / `core/actions.py` (`instance.terminate`) / `monitor/cloud_reaper.py` | Task 6 after 5 |
| `providers/image_registry.py` / `providers/registry.py` (`image_registry_for`) / `deploys/steps.py` (`ensure_ship`) | Task 7 after 2 |
| `providers/ssm.py` / `providers/registry.py` (`ssm_for`) / `deploys/steps.py` (`_put_env_file` call site only) | Task 8 after 2 |
| IAM daily audit Beat | Task 9 after 2 |
| SSH-CA writeup | Task 10 (SLIP) |
| acceptance + demo | Task 11 after MUST |

Tasks 3, 4, 7, 8, 9 are independent after Task 2 and **may run in parallel
worktrees**, provided each only **appends** its constructor to
`providers/registry.py` and does not rewrite Task 2's loader. Task 1 is
the schema wave — do not collide with it on `core/models.py`. Task 5
adds the `instance.create` ACTION_TIERS row; Task 6 adds
`instance.terminate`. If both touch `core/actions.py`, Task 6 waits for
Task 5 or only appends the terminate tuple. If Task 4 and Task 7 both
touch `Sites.jsx`, they do not — enroll UI is Targets, registry is not a
screen.

---

## Task 0 — Unblock `check.py --phase 5` (D-065…D-074)

**Title:** Phase-5 due set exists; PART-K moved to 5.5; `conformance-5`
excludes live tiers; sensitive paths claimed. Waives nothing that is MUST.

**Files created/touched:**
- `DECISIONS.md` — rows D-065…D-074 (text from the design note §5).
- `conformance/requirements.yaml` (sensitive) — bump `PART-K1-ZERO-INBOUND-HUB`,
  `PART-K2-REPLAY-AT-HUB`, `PART-K6-NO-INTERNAL-ACTIONS` to `phase: 5.5`.
  Leave `text:` / `text_hash:` untouched. Add the new ids in design note
  §3 (**no `tier:` key**). Do not change `text:` / `text_hash:` of any
  existing id. Do not mark full-text §I Phase 5 / §D5 (Azure, SSH-CA
  enablement, Key Vault, T3 aws parametrization) on any test.
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
  `provision/aws_enroll.py`.
- `docs/phase-5-design-note.md` / this file — already on the branch.

**Exact req ids proven:** none go green here except the gate shape. This
task makes the phase-5 due set honest. Do not create
`conformance/demos/phase-5.md` (a non-empty stub would verify
`P5-AWS-DEMO`).

**Tests to write:**
- `tests/test_conformance_gate.py` (extend) —
  `test_phase_5_due_set_includes_ec2_r53_enroll_iam_ssm_registry`;
  `test_part_k_ids_are_phase_5_5_not_5`;
  `test_new_phase_5_ids_have_no_tier`;
  `test_p5_aws_demo_names_phase_5_md`;
  `test_tls_b2_hub_dns01_stays_phase_4`.
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
  Do not add `t4` assertions. Do not add an all-tiers 5 target test that
  expects the target to exist.

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
- Nullable `Target.provider_ref` CharField (instance id). SSH rows stay
  null. Do not overload `host`.
- Python-only `DnsAccount.Provider.ROUTE53 = "route53"`. If
  makemigrations emits AlterField on `DnsAccount.provider`, fold it into
  `0012`. No new table.
- Python-only Kind values: `aws_iam_scope`, `aws_reaper`.
- Do **not** add `NetworkZone.kind`, `Site.tier`, `Site.secrets_mode`,
  or a `CloudAccount` table. `Secret.Kind.CLOUD_CREDENTIAL` already exists.
- Later tasks do **not** edit `core/models.py`.

**Tests:**
- `test_target_kind_aws_ec2_exists`
- `test_provider_ref_nullable_on_ssh_target`
- `test_dnsaccount_provider_route53_exists`
- `test_checkrun_kinds_aws_iam_scope_and_aws_reaper_exist`
- `test_no_networkzone_kind_and_no_site_tier`
- existing seed `burst-ec2-1` kind is now a legal choice (no model clean
  error)

**Dependencies:** Task 0.

---

## Task 2 — AWS credentials, IAM construction refuse, Settings tab, test-plane wall

**Title:** Vault-ref explicit keys; never default chain; IAM allowlist at
construction; Settings AWS tab; named allowlists; register C12 kinds.

**Files:** `providers/aws_creds.py` (new; boto3 allowed),
`providers/registry.py` (loader helpers only — not `cloud_provider_for`
yet), `core/test_mode.py` (`assert_test_aws`),
`hub/settings/base.py` (`HUB_AWS_CREDENTIALS_REF` → `AWS_CREDENTIALS_REF=""`,
`HUB_TEST_AWS_ACCOUNT_IDS`, `HUB_TEST_AWS_REGIONS`,
`HUB_AWS_HOURLY_BUDGET_USD` → `AWS_HOURLY_BUDGET_USD=""`),
`hub/settings/prod.py` (do not default the ref or allowlists on),
`core/zone_views.py` or new `core/aws_views.py` (`POST /api/v1/aws/connect/`),
`core/urls.py`, `frontend/src/screens/Settings.jsx` (AWS tab peer of
Cloudflare), `frontend/tests/settings-aws.test.ts`,
`monitor/alert_rules.py` (register every C12 kind that does not already
exist; do not raise them yet except construction `aws-scope`),
`requirements.txt` (pin `boto3`; botocore transitive),
`tests/test_aws_creds.py` (**must not import boto3/moto**).

**Do:**
- Load `Secret.Kind.CLOUD_CREDENTIAL` / `owner_type="aws"` /
  `owner_id=AWS_CREDENTIALS_REF`. JSON keys exactly
  `{access_key_id, secret_access_key}`. Extra keys / session token refuse.
- Pass explicit keys into any boto3 client this helper builds. A
  constructor that omits them is a failing test.
- Empty ref refuses. Do not scan the vault for leftover rows.
- `assert_test_aws(account_id, region)`: under `HUB_TEST_MODE` both
  allowlists must contain the values; empty allowlist refuses. Outside
  it, `purpose=test` tagged calls refuse.
- IAM helper refuses `*` / `AdministratorAccess` / off-prefix SSM /
  off-zone Route 53 / `iam:*` on an instance-profile document. Missing
  self-inspect = refuse. File `aws-scope:{account_id}` with refs, never
  secrets.
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

**Tests:**
- `test_empty_aws_credentials_ref_refuses`
- `test_explicit_keys_passed_into_client_never_default_chain`
- `test_session_token_or_extra_json_keys_refused`
- `test_empty_allowlist_refuses_live`
- `test_off_allowlist_account_or_region_refuses_under_hub_test_mode`
- `test_purpose_test_refuses_outside_hub_test_mode`
- `test_star_action_refuses_and_files_aws_scope`
- `test_administrator_access_refuses`
- `test_off_prefix_ssm_refuses`
- `test_off_zone_route53_refuses`
- `test_missing_iam_inspect_refuses`
- `test_finding_body_has_refs_never_secret`
- `test_settings_unconfigured_is_degraded_not_connected`
- `test_connect_observes_before_vault_write`
- `test_connect_201_never_echoes_keys`
- `test_connect_without_ref_does_not_invent_a_token_env`
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
public.

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
  `HttpPutResponseHopLimit=1`. Default SG has no 22/tcp `0.0.0.0/0`.
- Under `HUB_TEST_MODE`, spec without `tags.purpose=test` refuses.
- Host keys from `GetConsoleOutput` (Fake: immediate fingerprint).
  Timeout → raise, never TOFU. Fingerprint matches
  `paramiko.PKey.fingerprint` equality.
- `cloud_provider_for` loads via Task 2's helper, fail-closed, returns
  the EC2 adapter. Tests inject `FakeCloudProvider` and never need this
  constructor for pipeline defaults.
- Dummy static creds inside `mock_aws_ec2` (copy `mock_aws_kms`).

**Tests:**
- `test_cloud_provider_for_is_the_only_constructor`
- `test_create_instance_returns_host_key_fingerprint`
- `test_runinstances_requires_imdsv2_and_hop_limit_1`
- `test_default_sg_has_no_public_22`
- `test_purpose_test_required_under_hub_test_mode`
- `test_terminate_absent_is_success`
- `test_host_key_timeout_refuses_not_tofu`
- `test_estimate_hourly_cost_fake_is_0_05`
- `test_create_image_returns_id_and_is_not_a_secret_store`
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
  `DnsAccount.dns_token_ref` holds that same owner-id. Purpose wall uses
  `HUB_TEST_ZONE_SLUGS` for zone names. Changes only on that
  `DnsZone.provider_zone_id`.
- Public proxied sites stay Cloudflare. Do not pull DNS-01 into this
  task.
- File `r53-fail:{zone.pk}` on provider errors (refs, not tokens).

**Tests:**
- `test_route53_is_not_edge_protection`
- `test_upsert_proxied_true_raises`
- `test_capabilities_omit_proxied`
- `test_dns_provider_for_route53_fail_closed`
- `test_dns_provider_for_unknown_provider_still_refuses`
- `test_l5_against_route53_zone_is_notify_only`
- `test_edge_ref_on_route53_account_raises`
- `test_route53_never_loads_edge_token_ref`
- `test_changes_are_scoped_to_provider_zone_id`
- `test_route53_tests_do_not_import_boto3`
- existing Cloudflare `proxied=True` FakeDnsProvider tests stay green

**Dependencies:** Task 0 + Task 1 + Task 2. Do not edit `core/models.py`
(Provider.ROUTE53 is Task 1).

---

## Task 5 — Enroll: create → pin → provision + T1 + cost overlay + F8

**Title:** `instance.create` T1; pin before Transport; cost visible;
enroll-empty/error/degraded.

**Files:** `provision/aws_enroll.py` (new), `core/actions.py`
(`instance.create` T1, label “Create target”), enroll view/URL,
`frontend/src/screens/Targets.jsx`, `frontend/src/Tiers.jsx` (optional
`cost` on `T1Overlay`), `frontend/src/actions.js` (no presentation
rule change; T1 already `stepUp: "required"`),
`frontend/tests/actions.test.ts`, `frontend/tests/simulation-states.test.ts`
(`enroll-empty`, `enroll-error`, `enroll-degraded`),
`simulation/seed_v1.json` as needed, `tests/test_aws_enroll.py`.

**Do:**
- Playbook: `estimate_hourly_cost` → overlay shows it → T1 touch +
  type-the-name (`confirm_name` = intended host) → `create_instance` →
  write `Target.kind=aws_ec2`, `provider_ref`, `host=public_ip`,
  `host_key_fingerprint` → **then** `provision_host` over Transport.
- Empty / missing fingerprint refuses before Transport. Timeout waiting
  for keys files `aws-host-key-timeout:{name}` P1 and does not TOFU.
- Create failure files `aws-create-failed:{name}`. Cap exceeded files
  existing `budget-cap-hit` fingerprint `budget-cap-hit:aws` and refuses.
  Unconfigured/error estimate refuses — never `$0` as free.
- Targets empty state: one sentence + one button. No AWS ref → copy the
  provision CLI. Ref set → Create target. Copy never says “instance”.
- Do not add a 7th NAV item. Do not add a 4th F6 phone screen (overlay
  is already in `PHONE_SCOPE`).
- Run-twice: second pass zero mutating provider / Transport calls.

**Tests:**
- `test_instance_create_is_t1`
- `test_instance_create_refuses_without_recent_touch`
- `test_instance_create_requires_type_the_name`
- `test_pin_happens_before_any_transport`
- `test_empty_pin_still_refuses_transport`
- `test_host_key_timeout_does_not_tofu`
- `test_kind_aws_ec2_and_provider_ref_and_host_written`
- `test_cost_visible_on_overlay_before_confirm`
- `test_unconfigured_estimate_refuses_create`
- `test_budget_cap_hit_files_existing_kind`
- `test_enroll_run_twice_zero_mutating_calls`
- `test_totp_does_not_satisfy_instance_create`
- frontend: enroll-empty / enroll-error / enroll-degraded render on
  product screens; overlay shows `$0.05/h` (or the Fake number) in words
- frontend: `Create target` copy, never `instance`

**Dependencies:** Task 0 + Task 1 + Task 3. Prefer after Task 2 so the
Settings ref exists for the empty-state branch.

---

## Task 6 — Terminate, delete-terminates, cloud reaper

**Title:** `instance.terminate` T1; `target.delete` on `aws_ec2`
terminates then deletes; cloud reaper on the CloudProvider port;
Multipass reaper untouched.

**Files:** `core/actions.py` (`instance.terminate` T1, label “Terminate
target”), `core/views.py` (`TargetDeleteView` — terminate then delete
when `kind=aws_ec2`; absent == success), terminate view/URL,
`monitor/cloud_reaper.py` (new; **no boto3**), `monitor/drills.py`
(weekly FakeCloudProvider `purpose=test` plant + assert gone; do not
claim `HARNESS-REAPER-TEST-PLANE` covers AWS), `monitor/reaper.py`
(**do not add boto3; prefix `hub-t3-` stays**),
`tests/test_aws_terminate.py`, `tests/test_cloud_reaper.py`.

**Do:**
- `instance.terminate` is T1 (touch + type-the-name).
- `target.delete` stays T1. For `kind=aws_ec2`, call
  `cloud_provider_for(...).terminate_instance(provider_ref)` (or the
  injected port in tests) then delete the Django row. Already-absent ==
  success. SSH kind is unchanged (row delete only).
- Failures file `aws-terminate-failed:{target.pk}` P1.
- Cloud reaper: after D-066 wall, `list_tagged_instances({purpose: test})`
  then `terminate_instance`. Weekly drill plants Fake `purpose=test` and
  asserts gone.
- Run-twice zero mutating calls.

**Tests:**
- `test_instance_terminate_is_t1`
- `test_instance_terminate_refuses_without_recent_touch`
- `test_target_delete_on_aws_ec2_terminates_then_deletes`
- `test_target_delete_on_ssh_does_not_call_terminate`
- `test_terminate_absent_is_success`
- `test_cloud_reaper_respects_allowlist_and_purpose_test`
- `test_cloud_reaper_does_not_import_boto3`
- `test_multipass_reaper_unchanged_no_boto3`
- `test_weekly_drill_plants_fake_purpose_test_and_asserts_gone`
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
- `image_registry_for` fail-closed like `dns_provider_for`. Unconfigured
  → None (docker load), not a constructed open registry.
- Do not put boto3 in `providers/registry.py`.

**Tests:**
- `test_ensure_ship_none_still_docker_loads`
- `test_ensure_ship_with_registry_pushes_and_pulls`
- `test_fake_registry_requires_tls_and_auth`
- `test_push_cred_is_not_pull_cred`
- `test_pull_cred_is_per_target`
- `test_image_registry_for_unconfigured_returns_none`
- `test_image_registry_not_in_providers_registry_module_as_ecr_client`
- `test_nav_still_six`
- `test_image_registry_tests_do_not_import_boto3`
- `test_ensure_ship_run_twice_zero_mutating_calls`

**Dependencies:** Task 0 + Task 2. Do not edit `core/models.py`.

---

## Task 8 — SSM pull seam

**Title:** `providers/ssm.py` T1 fake; push stays default; instance
profile Get-only; never static AWS keys on a target.

**Files:** `providers/ssm.py` (new; `mock_aws_ssm`),
`providers/registry.py` (`ssm_for(target)`), `providers/fakes.py`
(`FakeSsm`), `deploys/steps.py` (branch in `_put_env_file` / caller:
`desired["secrets_mode"] == "ssm_pull"`), `tests/test_ssm.py`
(**no boto3/moto import**), extend `tests/test_no_token_exfiltration.py`.

**Do:**
- Paths `/deploy-hub/{target.pk}/…`. Hub SSM Put/Get/Delete/AddTags on
  `/deploy-hub/*` only. Instance profile Get-only on
  `/deploy-hub/{target}/*` — no Put, no `ec2:*`, no `iam:*`.
- Default `secrets_mode` is `push` (`_put_env_file` unchanged). Flip is
  desired/manifest, **not** `Site.tier`.
- Pull never writes `AWS_ACCESS_KEY_ID` / Hub IAM user keys / parameter
  values onto the target env file. File `ssm-fail:{target.pk}` on error
  (refs, not values).
- `ssm_for` fail-closed via Task 2's loader.

**Tests:**
- `test_push_remains_default`
- `test_ssm_pull_uses_prefix_deploy_hub_target`
- `test_instance_profile_policy_is_get_only`
- `test_no_aws_access_key_id_on_target`
- `test_no_ssm_value_in_finding_checkrun_log_task_arg_detail`
- `test_off_prefix_put_refuses`
- `test_secrets_mode_is_not_site_tier`
- `test_ssm_tests_do_not_import_boto3`
- `test_ssm_run_twice_zero_mutating_calls`

**Dependencies:** Task 0 + Task 2. Do not edit `core/models.py`. If Task 7
is in flight on `deploys/steps.py`, take it as parent or touch only the
env-file helper.

---

## Task 9 — IAM daily audit Beat

**Title:** Daily allowlist audit; same refuse as construction; CheckRun
`aws_iam_scope`.

**Files:** `monitor/tasks.py` (or `providers/aws_creds.py` consumer),
`hub/settings/base.py` Beat `aws-iam-scope-daily`,
`tests/test_aws_iam_audit.py` (**no boto3/moto import**).

**Do:**
- Beat loads the Hub user's attached/inline policies through the
  provider helper and refuses the same superset as Task 2.
  Drift files `aws-scope:{account_id}` P2. Clean run is SUCCEEDED with
  refs, never secrets, in `CheckRun.results`.
- Absent `AWS_CREDENTIALS_REF` → SKIPPED, not a T1-sibling green of a
  live id (there is no live MUST id).
- Do not mark a live-AWS req.

**Tests:**
- `test_daily_audit_refuses_star`
- `test_daily_audit_refuses_administrator_access`
- `test_daily_audit_files_aws_scope_on_drift`
- `test_absent_ref_skips_and_does_not_green_live_aws`
- `test_results_have_refs_never_secret`
- `test_aws_iam_audit_tests_do_not_import_boto3`

**Dependencies:** Task 0 + Task 2. Do not edit `core/models.py`
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

**Tests:** none required. Existing dual-key rotate tests stay green.

**Dependencies:** none for the writeup. MUST demo does not wait.

---

## Task 11 — Acceptance + demo

**Title:** `tests/acceptance/test_phase_5.py` + `conformance/demos/phase-5.md`

**Files:** those two. One acceptance test per §4 clause,
`@pytest.mark.acceptance(phase=5)`. Demo record is non-empty and names
the MUST path in design note §4. Do not claim live AWS. Do not claim
SSH-CA enablement. Do not claim DNS-01.

**Dependencies:** Tasks 1–9 (not 10).
