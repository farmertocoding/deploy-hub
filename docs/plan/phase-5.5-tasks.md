# Phase 5.5 tasks — Partner Deploy REST (T1 Fake intake)

SDD-ready work list for Implementers. Architect design note:
`docs/phase-5.5-design-note.md` r2 (panel §7 is binding). Do not start a task
whose dependencies are open. Do not start implementation from the design
session until the design panel records MERGE. Do not invent a path, env,
Finding fingerprint, action id, CheckRun key, or gate shape that the
design note does not name.

**Branch:** cut task branches from `p55-design` (which carries these two docs).
Never implement on `master`. Sensitive-path merges to `master` go through the
recorded expert-panel vote.

## Global constraints (every task)

- The Hub gains **zero** inbound partner/MCP/webhook routes. Six K3 endpoints
  live on the **intake** process. Extend the M2 “no non-tailnet route”
  standing test to also forbid Hub `/api/partner/*` and `/mcp`. Git-webhook
  is an **outbox type**, not a public intake or Hub route.
- `intake/**` is a separate process: not `INSTALLED_APPS`, not Hub
  `urlpatterns`. Intake never imports `vault`, `core`, `deploys`, `celery`,
  `hub`, `django`, `boto3`, `botocore`, `azure`, or `cloudflare`. Hub
  product modules (`monitor/`, `core/`, `hub/`, `deploys/`) never
  `import intake`; `intake_client_for` speaks HTTP or an injected
  `FakeIntakeClient`. T1 tests may import `intake`.
- Secrets through the vault. No `whsec_`, partner private key, or HMAC
  secret in a Finding, CheckRun, log, task arg, or `AuditEvent.detail`.
  Public keys are Partner columns, not vault rows. The Ed25519 private
  key is never vaulted. POST `partner.create` **201 returns** `hubk_*` +
  `whsec_` once (Enroll once-panel); GET never. AWS connect still never
  echoes pasted IAM keys.
- **Pinned env names:** `HUB_INTAKE_URL` → `INTAKE_URL` default `""`.
  `HUB_PARTNER_API_ENABLED` → `PARTNER_API_ENABLED` default `False`.
  `HUB_PARTNER_FLEET_MAX_SITES` → `PARTNER_FLEET_MAX_SITES` default `12`.
  **Do not invent `HUB_TEST_CF_TOKEN` / `HUB_TEST_AWS_TOKEN` /
  `HUB_TEST_PARTNER_TOKEN` / `HUB_WEBHOOK_SECRET` / `HUB_INTAKE_HMAC`.**
  Empty `INTAKE_URL` = poll no-op / SKIPPED, never a T1-sibling green,
  never a CheckRun insert every 10 s (upsert-at-most-one or skip persist).
- **`0012` is closed.** The only Hub migration is Task 1's `0013_phase55.py`.
  No `Site.tier`. No `Site.partner_id`. No `Target.tier`. No
  `NetworkZone.kind`. Destination order is Partner config.
- **`findings` is the canonical realtime topic.** Kind ≠ fingerprint except
  the two global C12 pins. Every “files …” line quotes design-note §7 C12
  **fingerprint**, not kind. `partner-site-hard-down` reuses
  `site-down:{name}`. `partner-aggregate-down` is
  `partner-aggregate-down:{partner.pk}` for N≥2, else reuses
  `host-down:{host}`. Prod host-down **must not** use
  `partner-aggregate-down`.
- Every new mutating playbook is run-twice with **zero** mutating Transport
  / mutating provider calls the second time (§D6, D-018).
- New alert kinds need a row in `monitor/alert_rules.py` first. Kinds and
  fingerprints are design-note §7 C12 only. Register `partner-replay`
  before first raise. Do not re-register existing partner kinds.
- Partner overflow calls `refuse` (in addition to `scaling/attack_gate.py`).
  Partner sites never land on the Hub host or a non-partner co-host.
- Do not claim a 24 h Hub-down (D-042). Do not enable live intake / CF-for-SaaS
  / HMAC verify / MCP (Joseph / OUT / slip as named). Do not complete
  Hub-central DNS-01. Do not invent a partner name.
- Reviewer never writes the code they review (D-014).
- Tiers: T1 = fakes/in-process. T2 = `hub-test-target`. T3 = Multipass.
  A `tier: t2|t3` req is verified only by a passed marked test (D-024).
  **New Phase 5.5 MUST ids are tier-less.** Q9 T2/T3 ids carry `tier:` so
  `--exclude-tier` drops them. Do not extend `VALID_TIERS` with `t4`.
- **Gates:** `conformance` and `review-round` stay `--phase 5
  --exclude-tier t2 --exclude-tier t3`. `conformance-5.5` is `--phase 5.5
  --exclude-tier t2 --exclude-tier t3` and is **not** a `review-round` or
  `nightly-gates` prereq. `conformance-5` stays phase 5 minus live.
  `conformance-3` stays all-tiers 3. No all-tiers 5.5. No `t4`.
  `PART-U1-NAMED-PARTNER` is due at `--phase 5.5` only (missing
  `named-partner.md` = uncovered on `conformance-5.5`, not on everyday
  `conformance`/`review-round`). T1 task merges do not wait on Joseph.
  Two consecutive clean `conformance-5.5` rounds wait on the interrupt.
  Do not stub that file. Do not waive U1 / PART-K / `failed` /
  `not-collected`.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the
  round they judge. Registry edits are Task 0.
- Fake intake / `FakeIntakeClient` remain the test default. Tests inject
  fakes; they do not bind a public `api.partners.<domain>`.
- UI copy says partner site / partner-tier target, never “instance” (D9)
  except the existing `single-instance` token. NAV stays six items.
  Settings Partners is **Create partner**, not Connect. Fake / empty
  `INTAKE_URL` / post-create never paints `Connected`.
- **Markers:** `conformance/check.py::collect_markers` counts only
  **function-level** `@pytest.mark.req("<id>")` on `def test_*`. Module
  `pytestmark` is invisible to that walker. Do not pin a MUST id only on
  `pytestmark`. No PART-* / UX-P55-* / P55-PARTNER-DEMO marker on a
  skip-unless or live test. No MUST id on a test that does not prove that
  clause. T1 tests never mark `PART-Q9-T2-CONTAINER` or
  `PART-Q9-T3-LIVE-PATH`. Never mark `PART-U1-NAMED-PARTNER` on a pytest.
- TDD: failing test first. Long "why" HEREDOC commits; no amend.

Protective cut (**D-075**): MUST = Tasks 0–9 and 11. Task 10 (HMAC/bearer
writeup) is the named slip line and does **not** block the MUST demo.
First slip = HMAC evaluation (not enablement). MCP is OUT.

## Parallel waves

| Shared file | Order |
|---|---|
| `conformance/requirements.yaml` / `Makefile` / `DECISIONS.md` / `WAIVERS.md` / `conformance/paths.yaml` / `.github/CODEOWNERS` | Task 0 |
| `core/models.py` / `0013_phase55.py` / `vault/models.py` (Kind only) | Task 1 after 0 (only writer) |
| `intake/**` / `tests/test_git_poller.py` (needles) / `tests/test_import_rule.py` | Task 2 after 0 |
| `monitor/intake_poll.py` / `core/partner_verify.py` / `conformance/fixtures/partner-signature-vectors.json` / `hub/settings/base.py` (Beat + env) / `monitor/alert_rules.py` (`partner-replay`) | Task 3 after **1+2** |
| `core/partner_templates.py` / `core/partner_jobs.py` (if used) / isolation in Hub re-validator / `scaling/attack_gate.py` (partner refuse only) | Task 4 after **1+3** |
| `core/partner_views.py` / `core/actions.py` (`partner.create`) / `core/zone_urls.py` / `frontend/src/screens/Settings.jsx` / `frontend/src/screens/Sites.jsx` / `frontend/src/Tiers.jsx` | Task 5 after **1** |
| `core/partner_webhooks.py` / `core/validators.py` (`validate_webhook_url`) / `providers/custom_hostname.py` / `providers/cloudflare.py` (capability on the `dns_provider_for` object) | Task 6 after **1** |
| `core/actions.py` (suspend / kill / takedown / destination_rank) / `hub/urls.py` / `monitor/partner_reaper.py` / `monitor/antinoise.py` / Settings+Sites kill/rank chrome | Task 7 after **1+5** |
| `monitor/intake_poll.py` (git-push type) / `deploys/poller.py` (enqueue only) | Task 8 after 3 |
| quota enforcement tests + fleet cap | Task 9 after **1+4** |
| HMAC writeup | Task 10 (SLIP) |
| acceptance + demo | Task 11 after MUST |

Independent after Task 1 (parallel worktrees): **Tasks 5 and 6**.
Task 2 does not need schema. Task 3 needs Partner + intake verifier.
Task 4 needs Hub re-verify. Task 7 needs ACTION_TIERS create row (Task 5)
before appending kill-switch tuples. Task 1 is the schema wave — do not
collide with it on `core/models.py`. If Task 5 and Task 7 both touch
`core/actions.py`, Task 7 waits for Task 5 or only appends.

---

## Task 0 — Unblock `check.py --phase 5.5` (D-075…D-085)

**Title:** Phase-5.5 due set exists; PART-K stay 5.5 and become due at
`conformance-5.5`; everyday `conformance`/`review-round` stay phase 5
minus live; sensitive paths claimed. Waives nothing that is MUST.

**Files created/touched:**
- `DECISIONS.md` — rows D-075…D-085 (text from the design note §5).
- `conformance/requirements.yaml` (sensitive) — leave
  `PART-K1-ZERO-INBOUND-HUB`, `PART-K2-REPLAY-AT-HUB`,
  `PART-K6-NO-INTERNAL-ACTIONS` at `phase: 5.5` with `text:` / `text_hash:`
  **untouched**. Add the fourteen new MUST ids plus two tiered Q9 ids by
  **copying** design note §3 (`phase: 5.5`; MUST ids have no `tier:`;
  `verify: test` except `P55-PARTNER-DEMO` and `PART-U1-NAMED-PARTNER`
  `verify: demo` naming the files in §3; one-sentence `text:` as written,
  including the expanded `UX-P55-PARTNERS` clause). Compute `text_hash:`
  with `python conformance/check.py --print-text-hashes`. Do not change
  `text:` / `text_hash:` of any existing id. Do not mark full-text
  §K3/K4/K5/K7 (live CF-for-SaaS, HMAC enablement, MCP, paid edge) on any
  T1 test.
- `tests/test_d023_actions_not_required.py` — **keep** `conformance`
  pinned to `--phase 5 --exclude-tier t2 --exclude-tier t3`. Pin
  `conformance-5.5` separately to `--phase 5.5 --exclude-tier t2
  --exclude-tier t3`. Leave `conformance-3` as all-tiers `--phase 3` with
  **no** `--exclude-tier`. Leave `conformance-5` as `--phase 5
  --exclude-tier t2 --exclude-tier t3`. Leave `conformance-4` as
  `--phase 4 --exclude-tier t2 --exclude-tier t3`. Assert
  `conformance-5.5` is **not** a `review-round` prereq.
- `WAIVERS.md` — **no new MUST waiver.** Do not retire TLS-B2 / SEC-B2 /
  REL-P2 / LE-staging. Do not waive PART-K or PART-U1. Do not waive
  `failed` / `not-collected`.
- `Makefile` — **leave** `conformance` as `--phase 5 --exclude-tier t2
  --exclude-tier t3`. Add `conformance-5.5` as `--phase 5.5
  --exclude-tier t2 --exclude-tier t3`. Leave `conformance-5` as **phase
  5 minus live**. Leave `conformance-4` / `conformance-3.5` minus-live.
  Leave `conformance-3` as **all-tiers Phase 3**. Add `conformance-5.5`
  to `.PHONY`. Do **not** add `conformance-5.5` as a `review-round` or
  `nightly-gates` prerequisite. Do **not** add an all-tiers 5.5 target.
  Do **not** add `t4`. `nightly-gates` still uses `conformance-3`.
- `conformance/paths.yaml` + `.github/CODEOWNERS` — claim the
  sensitive-path additions in the design note (files that do not exist
  yet are listed): `monitor/intake_poll.py`, `core/partner_webhooks.py`,
  `providers/custom_hostname.py`, `core/partner_views.py`,
  `monitor/partner_reaper.py`, `core/partner_verify.py`,
  **`core/partner_templates.py`**, **`core/partner_jobs.py`**.
  `intake/**` already listed.
- `docs/phase-5.5-design-note.md` / this file — already on the branch.

**Exact req ids proven:** none go green here except the gate shape. This
task makes the phase-5.5 due set honest. Do not create
`conformance/demos/phase-5.5.md` or `conformance/demos/named-partner.md`
(a non-empty stub would verify those demo ids).

**Tests to write** (function-level `@pytest.mark.req` is N/A — no MUST id
greens here):
- `tests/test_conformance_gate.py` (extend) —
  `test_phase_5_5_due_set_includes_all_section_3_must_ids` asserts the live
  registry contains all fourteen §3 MUST ids at `phase: 5.5` with **no
  `tier:` key**: `PART-INTAKE-PROCESS`, `PART-K3-ENDPOINTS`,
  `PART-HUB-POLL`, `PART-Q9-SHARED-VECTORS`, `PART-ISOLATION`,
  `PART-TEMPLATES`, `PART-WEBHOOKS`, `PART-CUSTOM-HOSTNAME`,
  `PART-KILL-SWITCH`, `PART-M2-GIT-WEBHOOK`, `PART-U2-QUOTAS`,
  `UX-P55-PARTNERS` (`verify: test`) and `P55-PARTNER-DEMO` /
  `PART-U1-NAMED-PARTNER` (`verify: demo`, naming
  `conformance/demos/phase-5.5.md` and
  `conformance/demos/named-partner.md` respectively);
  `test_part_k_ids_stay_phase_5_5_and_are_due_at_phase_5_5`;
  `test_new_phase_5_5_must_ids_have_no_tier`;
  `test_part_q9_t2_is_tier_t2`;
  `test_part_q9_t3_is_tier_t3`;
  `test_p55_partner_demo_names_phase_5_5_md`;
  `test_part_u1_names_named_partner_md_and_file_is_absent`;
  `test_p5_aws_demo_still_phase_5`;
  `test_valid_tiers_still_t1_t2_t3_only`;
  `test_no_all_tiers_5_5_target` (assert the Makefile target does **not**
  exist);
  `test_part_k_text_and_text_hash_untouched` (compare to the frozen
  hashes in the registry as of `4f30c7a`).
- `tests/test_makefile_nightly.py` — **rewrite** any pin that
  `conformance` is `--phase 5.5` (r1 named
  `test_review_round_conformance_is_phase_5_5_minus_live_tiers` as a
  rewrite of the review-round recipe — that pin must not land).
  Replacement: `test_review_round_conformance_is_still_phase_5_minus_live_tiers`
  (keep the current phase-5 pin on `conformance`:
  `test_review_round_conformance_is_phase_5_minus_live_tiers` stays;
  `--phase 5.5` is **not** in the `conformance` recipe). New:
  `test_conformance_5_5_is_phase_5_5_minus_live_tiers`;
  `test_conformance_5_5_is_not_a_review_round_or_nightly_prereq`.
  Keep `test_nightly_gates_use_conformance_3` unchanged. Keep
  `test_conformance_5_is_phase_5_minus_live_tiers` unchanged
  (`conformance-5` stays). Also:
  `test_conformance_5_5_target_exists`;
  `test_conformance_5_still_phase_5_minus_live_tiers`;
  `test_conformance_3_still_all_tiers_phase_3`.
  Do not add a test that claims `conformance-3` excludes live tiers.
- `tests/test_d023_actions_not_required.py` — keep the `conformance`
  recipe pin at `--phase 5` with both excludes; pin `conformance-5.5`
  separately; assert `conformance-5.5` is not a `review-round` prereq.

**Dependencies:** none.

---

## Task 1 — Schema wave `0013_phase55.py`

**Title:** Partner + PartnerSite + Hub replay/idempotency + AuditEvent.partner
FK. `0012` stays closed. Isolation is PartnerSite + dedicated Targets —
no `Site.partner_id`, no `Target.tier`.

**Files:** `core/models.py` (**this task is the only writer this phase**),
`core/migrations/0013_phase55.py`, `vault/models.py` (`Secret.Kind.WEBHOOK_SECRET`
only), `vault/migrations/0003_phase55.py` if AlterField is generated,
`tests/test_partner_schema.py`.

**Do:**
- `Partner` as §7 C2 (defaults: `max_sites=5`, `deploys_per_day=50`,
  `domains=5`; `destination_order=[]`; two Ed25519 pubkey slots).
- `PartnerSite` FK Partner + OneToOne Site; `tenant_ref`; unique
  `(partner, tenant_ref)`.
- `PartnerReplayNonce` unique `(partner, nonce)`.
- `PartnerIdempotencyKey` unique `(partner, key)` + `params_hash` +
  stored first response.
- `AuditEvent.partner` nullable FK `SET_NULL`; **remove** `partner_id_stub`.
- Python-only CheckRun kinds `partner_reaper`, `intake_poll`. Do **not**
  AlterField CheckRun.
- `Secret.Kind.WEBHOOK_SECRET = "webhook_secret"`. HMAC kind does **not**
  land. If makemigrations emits AlterField on `Secret.kind`, fold it into
  vault `0003_phase55.py`.
- Do **not** add `Site.tier`, `Site.partner_id`, `Target.tier`,
  `NetworkZone.kind`, or a PartnerTemplate table. Partner-tier iff pk ∈
  some Partner `destination_order`. The binding is `PartnerSite`.
- Later tasks do **not** edit `core/models.py`.

**Exact req ids proven:** none (schema enables later markers; do not hang
a PART-* id on a model-choice test).

**Tests:**
- `test_partner_and_partnersite_exist`
- `test_partnersite_unique_tenant_ref_per_partner`
- `test_replay_nonce_unique_per_partner`
- `test_idempotency_key_unique_per_partner`
- `test_auditevent_partner_fk_replaces_stub`
- `test_checkrun_kinds_partner_reaper_and_intake_poll_exist`
- `test_no_site_tier_and_no_networkzone_kind`
- `test_no_site_partner_id`
- `test_no_target_tier`
- `test_partner_quota_defaults_are_5_50_5`
- `test_secret_kind_webhook_secret_exists`
- `test_secret_kind_has_no_hmac`

**Dependencies:** Task 0.

---

## Task 2 — Intake process skeleton + six endpoints + Fake outbox + import wall

**Title:** `intake/**` WSGI process; six K3 routes; mesh-only outbox;
credential-free import wall; Hub URLConf still zero partner/MCP inbound;
verify stub fail-closed; Hub does not import intake.

**Files:** `intake/app.py` (WSGI `application`), `intake/__main__.py`,
`intake/verify.py` (Ed25519 edge verifier; shared vectors land in Task 3 —
this task can take a **fail-closed** stub interface), `intake/outbox.py`
(Fake in-memory outbox), `intake/fake.py`, `requirements.txt`
(`cryptography` pin if not already a declared dep),
`tests/test_intake_process.py` (**must not import boto3/moto**; may import
`intake`), `tests/test_git_poller.py` (extend needles/paths per §7 C3),
`tests/test_import_rule.py` (add `intake` to the SDK scan list; add the
credential-free wall; add Hub-does-not-import-intake).

**Do:**
- Stdlib WSGI only. No Django, no DRF, no Flask/FastAPI/Starlette.
- Public routes exactly the six K3 families in §7 C3. Mesh `/internal/outbox`
  and `/internal/ack` are **not** on the public listener. Git-push is not
  a 7th public route.
- Fake outbox holds signed jobs. Public client cannot read it.
- Intake holds public keys + counters + outbox only. No webhook secret.
- Hub urlpatterns still contain neither `/api/partner` nor `/mcp`. Extend
  TRIGGER_PATHS / WEBHOOK_NEEDLES as §7 C3.
- Pin `cryptography` in `requirements.txt` if Task 2 is the first importer.
  Intake may import `cryptography`; it may not import Django.
- Verify stub is **fail-closed**: unsigned / invalid signature → 401/403,
  never 201/202. 201/202 tests sign with a fixture key (or move those
  status tests to Task 3).
- Hub product modules never `import intake`.

**Exact req ids:** `PART-INTAKE-PROCESS`, `PART-K3-ENDPOINTS`,
`PART-K1-ZERO-INBOUND-HUB`. Function-level `@pytest.mark.req` on the named
tests below. No live / skip-unless marker.

**Tests:**
- `test_intake_not_in_installed_apps` — `PART-INTAKE-PROCESS`
- `test_intake_does_not_import_vault_core_deploys_celery_hub_django_cloud_sdks` — `PART-INTAKE-PROCESS`
- `test_hub_product_modules_do_not_import_intake` — `PART-INTAKE-PROCESS`
- `test_public_listener_is_six_k3_routes_only` — `PART-K3-ENDPOINTS`
- `test_public_client_cannot_hit_internal_outbox` — `PART-INTAKE-PROCESS`
- `test_unsigned_post_is_not_201` — `PART-INTAKE-PROCESS` (fail-closed stub)
- `test_post_sites_returns_201_shape` — `PART-K3-ENDPOINTS` (signed)
- `test_post_deployments_returns_202` — `PART-K3-ENDPOINTS` (signed)
- `test_delete_absent_is_204` — `PART-K3-ENDPOINTS`
- `test_hub_urlconf_has_no_api_partner_or_mcp` — `PART-K1-ZERO-INBOUND-HUB`
- `test_hub_candidate_partner_and_mcp_paths_404` — `PART-K1-ZERO-INBOUND-HUB`
- `test_intake_is_not_a_django_app`
- **no live intake test**

**Dependencies:** Task 0. Do not edit `core/models.py`.

---

## Task 3 — Hub poller + re-verify + replay + idempotency (shared vectors)

**Title:** Beat 10 s on `probes`; Hub re-verifies Ed25519; Postgres nonce
cache + 24 h idempotency; shared vectors vs both verifiers (incl.
quota-exceeded); C12 `partner-replay`; empty URL does not flood CheckRun.

**Files:** `monitor/intake_poll.py` (new; `intake_client_for` fail-closed;
`FakeIntakeClient`; **must not** `import intake`), `core/partner_verify.py`
(new; Hub re-verifier), `intake/verify.py` (complete against the shared
file), `conformance/fixtures/partner-signature-vectors.json`,
`hub/settings/base.py` (`HUB_INTAKE_URL` → `INTAKE_URL=""`,
`HUB_PARTNER_API_ENABLED` → `PARTNER_API_ENABLED=False`,
`HUB_PARTNER_FLEET_MAX_SITES` → `PARTNER_FLEET_MAX_SITES=12`, Beat
`poll-intake-outbox` → `monitor.tasks.poll_intake_outbox` `schedule: 10.0`;
`monitor.*` already on `probes`), `monitor/tasks.py` (thin wrapper),
`monitor/alert_rules.py` (register `partner-replay` only),
`hub/settings/prod.py` (do not default the flag or intake URL on),
`tests/test_intake_poll.py`, `tests/test_partner_verify.py`.

**Do:**
- Shared vectors: valid / expired / replayed / mutated-body / idempotency
  match / idempotency mismatch / quota exceeded. Both verifiers import
  that file. Implementations must not share code. Both load the
  quota-exceeded vector; Hub refuse wins (intake “allow” cannot override).
- Headers and canonical string as §7 C4. 5-minute window. Nonce TTL 10 min.
  Idempotency 24 h; param mismatch 422.
- Hub rejects a replay **even when Fake intake forwards it**. File
  fingerprint `partner-replay:{partner.pk}`.
- Empty `INTAKE_URL` → no-op, SKIPPED, do not file P1
  `partner-intake-unreachable`, **do not insert a CheckRun per 10 s tick**
  (upsert-at-most-one or skip persist). Do not add `intake_poll` to
  `DRILL_PERIODS`. Configured success/failure may persist on transition.
- N=3 consecutive poll failures → fingerprint `hub-outbox-poll-failing`.
  Last success > 5 min → fingerprint `partner-intake-unreachable`. Pass
  `fingerprint=` explicitly for those two global pins.
- Batch cap 20; 0–2 s jitter inside the task. Constructor fail-closed.
- Global `PARTNER_API_ENABLED` default False: poll still runs (so
  unreachable can fire) but validated jobs do not become Deployments until
  Task 4 + the flag (Task 7 enables). This task may persist outbox rows
  and reject bad signatures without creating Deployments if Task 4 is not
  merged yet — then Task 4 wires Deployment create.
- No invented token env.

**Exact req ids:** `PART-HUB-POLL`, `PART-Q9-SHARED-VECTORS`,
`PART-K2-REPLAY-AT-HUB`. Function-level `@pytest.mark.req` on the named
tests below. No live / skip-unless marker.

**Tests:**
- `test_vectors_valid_passes_both_verifiers` — `PART-Q9-SHARED-VECTORS`
- `test_vectors_expired_rejected_by_both` — `PART-Q9-SHARED-VECTORS`
- `test_vectors_mutated_body_rejected_by_both` — `PART-Q9-SHARED-VECTORS`
- `test_vectors_replay_rejected_by_hub_even_if_intake_forwards` — `PART-K2-REPLAY-AT-HUB`
- `test_vectors_quota_exceeded_hub_authoritative` — `PART-Q9-SHARED-VECTORS`
  (both verifiers load the shared quota-exceeded vector; Hub refuse wins)
- `test_idempotency_match_returns_first_response` — `PART-Q9-SHARED-VECTORS`
- `test_idempotency_mismatch_is_422` — `PART-Q9-SHARED-VECTORS`
- `test_beat_interval_is_10s_on_probes` — `PART-HUB-POLL`
- `test_empty_intake_url_skips_and_does_not_file_p1` — `PART-HUB-POLL`
  (also: repeated ticks do not grow `CheckRun` count; do not file
  `partner-intake-unreachable`)
- `test_n3_poll_failures_file_hub_outbox_poll_failing` — `PART-HUB-POLL`
- `test_unreachable_over_5_min_files_partner_intake_unreachable` — `PART-HUB-POLL`
- `test_intake_client_for_is_fail_closed` — `PART-HUB-POLL`
- `test_finding_fingerprint_is_partner_replay_partner_pk` — `PART-K2-REPLAY-AT-HUB`
- `test_no_whsec_or_private_key_in_finding_detail`
- `test_verifiers_do_not_share_a_module`
- **no live intake test**. Do not mark `PART-Q9-T2-CONTAINER` or
  `PART-Q9-T3-LIVE-PATH`.

**Dependencies:** Task 0 + Task 1 + Task 2.

---

## Task 4 — Partner isolation + template-only refuse + K6 tests

**Title:** Validated jobs become Deployments isolated by Partner/PartnerSite;
template-only; K6 router allowlist; V3 no job commands; overflow refuse;
cross-partner IDOR 404.

**Files:** `core/partner_templates.py` (new; one digest-pinned fixture;
**claimed in Task 0**), `images/partner-t1-static/` (T1 fixture image
sources), `conformance/fixtures/partner-t1-template.digest`, Hub
re-validator / job materialize next to the poller (ordinary Hub module
Task 3 already owns — extend `monitor/intake_poll.py` or
`core/partner_jobs.py`, which Task 0 claimed — **not** `core/models.py`),
`scaling/attack_gate.py` (partner overflow refuse; do not remove
`refuse_if_attack`), `tests/test_partner_isolation.py`,
`tests/test_partner_k6.py`.

**Do:**
- Materialize a validated `partner-job` into an ordinary Deployment bound
  by `PartnerSite`. Querysets filter on Partner. Partner A 404s on B’s ids
  (not 403). Do not `import intake`.
- Refuse: Hub host, Target not in this Partner `destination_order`, Target
  that already hosts a non-`PartnerSite`, empty `destination_order`,
  partner Dockerfile / build / git-as-source / unconstrained image,
  scheduled-job create/edit on a `PartnerSite`, overflow scale.
- Own-server (`kind=ssh`) destination refuses unless
  `collect_payload["tunnel"] is True`. Partner-base ≠ a non-partner Site
  domain.
- Template fixture: docker load / Fake registry of the digest-pinned
  image only. Not `catalog/` / `AppliedCatalogEntry`.
- K6: the intake/partner **router** maps to no `ACTION_TIERS` T1/T2
  **internal** id (`target.delete`, `key.export`, `kek.rotate`,
  `ssh.rotate`, `instance.create`, `instance.terminate`, `dns.change`,
  `site.auto_mode`, and the new `partner.*` operator ids). Operator chrome
  may have those ids; the partner router must not call them.
- `PARTNER_API_ENABLED` False → jobs stay in outbox / rejected, no
  Deployment. True path is tested with `override_settings`.

**Exact req ids:** `PART-ISOLATION`, `PART-TEMPLATES`,
`PART-K6-NO-INTERNAL-ACTIONS`. Function-level `@pytest.mark.req` on the
named tests below. No live / skip-unless marker.

**Tests:**
- `test_partner_router_maps_to_no_action_tiers_t1_t2` — `PART-K6-NO-INTERNAL-ACTIONS`
- `test_partner_a_404s_on_partner_b_ids` — `PART-ISOLATION`
- `test_no_site_tier_column` — `PART-ISOLATION`
- `test_no_site_partner_id_and_no_target_tier` — `PART-ISOLATION`
- `test_hub_host_refuses` — `PART-ISOLATION`
- `test_non_partner_cohost_refuses` — `PART-ISOLATION`
- `test_empty_destination_order_refuses_create` — `PART-ISOLATION`
- `test_overflow_scale_refuses_partner_site` — `PART-ISOLATION`
- `test_scheduled_job_create_on_partnersite_refuses` — `PART-K6-NO-INTERNAL-ACTIONS`
- `test_dockerfile_or_git_source_refuses` — `PART-TEMPLATES`
- `test_unconstrained_image_refuses` — `PART-TEMPLATES`
- `test_digest_pinned_fixture_template_deploys` — `PART-TEMPLATES`
- `test_template_is_not_applied_catalog_entry` — `PART-TEMPLATES`
- `test_own_server_without_tunnel_refuses` — `PART-ISOLATION`
- `test_flag_off_does_not_create_deployment`
- `test_materialize_run_twice_zero_mutating_calls` — `PART-ISOLATION`

**Dependencies:** Task 0 + Task 1 + Task 3. Do not edit `core/models.py`.

---

## Task 5 — Settings Partners tab + ACTION_TIERS create + F8

**Title:** Settings Partners tab is Create partner; `partner.create` T1;
201 returns `hubk_*` + `whsec_` once; GET never; Fake/unconfigured/
post-create never Connected; F8 partner-intake-empty/error/degraded;
NAV stays six.

**Files:** `core/actions.py` (`partner.create` T1, label “Create partner”),
`core/partner_views.py` (new; `POST /api/v1/partners/` — do **not** put
this on `core/urls.py`), `core/zone_urls.py` (include `partners/`),
`frontend/src/screens/Settings.jsx` (Partners tab after AWS; Create
partner not Connect; empty-order honesty copy; never `\bConnected\b`),
`frontend/src/screens/Sites.jsx` (All/Mine/Partner filter + partner badge
symbol + words; hide adopt and job-create on partner site detail),
`frontend/src/screens/Findings.jsx` (entity `partner:{slug}` filter),
`frontend/src/Tiers.jsx` (no cost on partner T1; other T1 ids unchanged
this task — Task 7 may add optional `summary`),
`frontend/src/Chrome.jsx` (**do not** add a 7th NAV id),
`frontend/tests/nav.test.ts` (SETTINGS_TABS order),
`frontend/tests/settings-partners.test.ts`,
`frontend/tests/simulation-states.test.ts` (`partner-intake-empty`,
`partner-intake-error`, `partner-intake-degraded` on `REQUIRED_STATE_IDS`;
PartnerSite-bound seed, **never** `tier: partner`),
`simulation/seed_v1.json` (PartnerSite-bound site, **not** `Site.tier`,
never a committed-partner name),
`core/checklist.py` (**do not** add `connect_partner`),
`tests/test_partner_create.py`.

**Do:**
- `partner.create` is T1 (touch + type-the-name; `confirm_name` = slug).
  Mint Ed25519 in-Hub; **201 returns** `hubk_test_` (or `hubk_live_`
  outside `HUB_TEST_MODE`) + `whsec_` **once**; persist **public** keys
  on Partner; `vault.put` `WEBHOOK_SECRET` under `owner_type="partner"`.
  Private key is never a Partner column and is never vaulted. GET / list
  never echo `hubk_` / `whsec_`. AuditEvent.detail / logs / task args /
  Findings / CheckRuns contain no `hubk_`, `whsec_`, PEM, or raw key
  bytes. UI is the Enroll once-panel (copy + “I saved them”; closing
  loses them; no persistent secret field). AWS connect still never
  echoes pasted IAM keys.
- Empty Partners tab = one sentence + the T1 **Create partner** button
  (not Connect, not a second Intake console). Unconfigured / Fake-only /
  empty `INTAKE_URL` / **post-create** = degraded, never `\bConnected\b`;
  name the Fake. `INTAKE_URL` stays env.
- List destination order on the tab: empty order is visible (“partner-site
  create will refuse”); default dedicated cloud first. Ranker **save**
  waits for Task 7’s T2 row.
- NAV stays six. SETTINGS_TABS =
  `security, cloudflare, aws, partners, developer, vault`.
- F8 seed+render against the product tab, not a demo pane.
  `REQUIRED_STATE_IDS` += the three intake ids + PartnerSite-bound site
  (filter + `partner` badge). Hide adopt and job-create on partner site
  detail. SLA copy is response-time, not 99.9%.
- Copy never says “instance” except `single-instance`.
- Do not add a 4th F6 phone screen.

**Exact req ids:** `UX-P55-PARTNERS`. Function-level `@pytest.mark.req` on
the named tests below — including secrets-once, never-Connected,
Create-partner, F8 seed/badge/hide-adopt/copy, **not** tab-existence
alone. `PART-KILL-SWITCH` waits for Task 7 (create is T1 here; mark
`PART-KILL-SWITCH` only on Task 7 tests that prove the kill layers).
Task 7 chrome tests also mark `UX-P55-PARTNERS`. No live / skip-unless
marker.

**Tests:**
- `test_partner_create_is_t1` — `UX-P55-PARTNERS`
- `test_partner_create_refuses_without_recent_touch` — `UX-P55-PARTNERS`
- `test_partner_create_requires_type_the_name` — `UX-P55-PARTNERS`
- `test_totp_does_not_satisfy_partner_create` — `UX-P55-PARTNERS`
- `test_create_201_returns_hubk_and_whsec_once` — `UX-P55-PARTNERS`
- `test_get_never_echoes_hubk_or_whsec` — `UX-P55-PARTNERS`
- `test_create_does_not_put_hubk_or_whsec_in_audit_or_logs` — `UX-P55-PARTNERS`
- `test_private_key_is_not_a_partner_column_and_not_vaulted` — `UX-P55-PARTNERS`
- `test_settings_is_create_partner_not_connect` — `UX-P55-PARTNERS`
- `test_settings_unconfigured_is_degraded_not_connected` — `UX-P55-PARTNERS`
- `test_settings_post_create_fake_or_empty_intake_never_connected` — `UX-P55-PARTNERS`
- `test_nav_still_six` — `UX-P55-PARTNERS`
- `test_checklist_has_no_connect_partner` — `UX-P55-PARTNERS`
- `test_settings_tabs_partners_after_aws` — `UX-P55-PARTNERS`
- `test_copy_does_not_say_instance` — `UX-P55-PARTNERS`
- `test_settings_partners_has_no_99_9_uptime_sla` — `UX-P55-PARTNERS`
- `test_sites_all_mine_partner_filter_and_partner_badge` — `UX-P55-PARTNERS`
- `test_hide_adopt_and_job_create_on_partner_site_detail` — `UX-P55-PARTNERS`
- `test_f8_seed_is_partnersite_never_site_tier_partner` — `UX-P55-PARTNERS`
- frontend: partner-intake-empty / error / degraded render on product
  screens; Sites filter + partner badge (symbol + words); Findings
  entity filter; Enroll once-panel after 201 (prefixes gone from DOM
  after dismiss); `REQUIRED_STATE_IDS` includes the three intake ids —
  `UX-P55-PARTNERS`
- **no live partner test**

**Dependencies:** Task 0 + Task 1. Do not edit `core/models.py`.

---

## Task 6 — Webhooks T1 fake sink + Fake CustomHostname TXT-before-serve

**Title:** Standard Webhooks Hub egress; B10 HTTPS validator; re-resolve
at every delivery; Fake CustomHostname on the `dns_provider_for` object;
unverified never served.

**Files:** `core/validators.py` (`validate_webhook_url`),
`core/partner_webhooks.py` (new; Hub signer + Fake sink; **no** intake
import of this module), `providers/custom_hostname.py` (new; helpers
only — **no** vault token load, **no** `api_request`, **no** Cloudflare
HTTP client), `providers/cloudflare.py` (`capabilities` on the
`dns_provider_for` object adds `custom_hostname`; create/status/TXT live
on that object), `providers/base.py` (docstring / capability note only),
`providers/fakes.py` (Fake CustomHostname), `providers/registry.py`
(construction stays `dns_provider_for` only),
`requirements.txt` (`standardwebhooks` pin for the reference verifier),
`tests/test_partner_webhooks.py`, `tests/test_custom_hostname.py`.

**Do:**
- `validate_webhook_url`: HTTPS-only, ports `{None, 443}`, then B10
  address checks (loopback / link-local including 169.254.169.254 /
  private / reserved / multicast / unspecified / CGNAT / `.local`
  suffixes). Do not reuse `validate_git_url` (ssh/22 would pass).
- **Re-resolve and re-run B10 on every delivery.** Any blocked address
  refuses the POST. Redirects off, or `Location` re-validated. Do **not**
  inherit git’s clone-off-Hub TOCTOU exception.
- Sign Standard Webhooks exact. T1 Fake sink + reference verifier (unit,
  no live POST). Retry ~5× / 24 h; sustained failure disables and files
  fingerprint `hub-egress-degraded:partner:{pk}`.
- `whsec_` vaulted Hub-side only. Never on intake. Never in
  AuditEvent.detail.
- Fake CustomHostname: TXT ownership before anything is served.
  Unverified = no Caddy route. Partner-base ≠ Joseph prod domain (reuse
  Task 4 refuse). No new ACME / DNS-01. Live CF-for-SaaS is not this task.
- Route 53 capabilities still omit `custom_hostname`. Fake-without-the-flag
  omits it. `EdgeProtection` stays CF-only.
- AST-scan the analog of `test_dns_provider_for_is_the_only_construction_path`:
  helpers and Hub modules do not construct a Cloudflare client.

**Exact req ids:** `PART-WEBHOOKS`, `PART-CUSTOM-HOSTNAME`. Function-level
`@pytest.mark.req` on the named tests below. No live / skip-unless marker.

**Tests:**
- `test_http_or_ssh_webhook_url_refuses` — `PART-WEBHOOKS`
- `test_loopback_linklocal_private_cgnat_webhook_url_refuses` — `PART-WEBHOOKS`
- `test_delivery_re_resolves_and_refuses_rebind_to_metadata` — `PART-WEBHOOKS`
- `test_standard_webhooks_signature_verifies_with_reference_lib` — `PART-WEBHOOKS`
- `test_whsec_not_on_intake_and_not_in_detail` — `PART-WEBHOOKS`
- `test_sustained_failure_disables_and_files_hub_egress_degraded` — `PART-WEBHOOKS`
- `test_unverified_hostname_is_not_served` — `PART-CUSTOM-HOSTNAME`
- `test_txt_before_serve` — `PART-CUSTOM-HOSTNAME`
- `test_custom_hostname_is_capability_on_dns_provider_for_object` — `PART-CUSTOM-HOSTNAME`
- `test_helpers_do_not_construct_a_cloudflare_client` — `PART-CUSTOM-HOSTNAME`
- `test_route53_has_no_custom_hostname_capability` — `PART-CUSTOM-HOSTNAME`
- `test_no_acme_or_dns01_in_custom_hostname_module` — `PART-CUSTOM-HOSTNAME`
- `test_webhook_run_twice_zero_mutating_calls` — `PART-WEBHOOKS`
- **no live CF-for-SaaS test**

**Dependencies:** Task 0 + Task 1. Do not edit `core/models.py`.

---

## Task 7 — Kill switches + reaper orphan + O1 P2 classifier + rank/kill chrome

**Title:** T1 suspend + api_kill_switch; T2 site_takedown; global default
OFF; Fake Transport stop+detach+revoke; partner reaper; O1 classifier
reads Partner FK; Settings/Sites kill-switch and destination-rank chrome.

**Files:** `core/actions.py` (append `partner.suspend` T1,
`partner.api_kill_switch` T1, `partner.site_takedown` T2,
`partner.destination_rank` T2 — after Task 5’s create row),
`hub/urls.py` (suspend / kill-switch / takedown /
`POST /api/v1/partners/<int:pk>/destination-rank/` — **not**
`core/urls.py`), `core/partner_views.py` (operator views),
`monitor/partner_reaper.py` (new; **no boto3, no Multipass**),
`monitor/drills.py` (weekly Fake orphan plant + assert gone + persist
`CheckRun.Kind.PARTNER_REAPER`; do **not** add `intake_poll` to
`DRILL_PERIODS`), `monitor/reaper.py` (**do not add boto3; prefix
`hub-t3-` stays**), `monitor/cloud_reaper.py` (**untouched**),
`monitor/antinoise.py` (`_file_open` / `_env_role_label` — PartnerSite
membership, stop mapping every `host-down:` to
`partner-aggregate-down`), `frontend/src/screens/Settings.jsx` (append
ranker save after the T2 row exists; enable is T1 not a toggle; suspend
control), `frontend/src/screens/Sites.jsx` (takedown T2 on partner site
detail), `frontend/src/Tiers.jsx` (optional T1Overlay `summary`; partner
T1 omits cost; other T1 ids omit summary),
`frontend/tests/simulation-states.test.ts` (`REQUIRED_STATE_IDS` +=
kill-switch overlay + destination-order confirm),
`frontend/tests/settings-partners.test.ts` (ranker + never-Connected +
Create partner), `tests/test_partner_kill_switch.py`,
`tests/test_partner_reaper.py`, `tests/test_partner_o1.py`.

**Do:**
- Global `PARTNER_API_ENABLED` default False. Enabling is T1 (type
  `partner-api`, chrome label “Enable partner API” when OFF) — never a
  toggle. Suspend is T1 (type slug): stop Fake Transport containers,
  detach routes, revoke Hub-side key, set `suspended=True`. Overlay
  `summary` must render stop containers / detach routes / revoke key.
  Takedown is T2 on partner site detail: `{domain} route → 410`.
  Auto-trigger files fingerprint `partner-kill-switch:{partner.pk}`.
  CSAM auto-suspend stays overlay-free.
- Destination rank T2 via `POST /api/v1/partners/<int:pk>/destination-rank/`.
  Own-server (`kind=ssh`) ConfirmDialog `summary` is the K5 honesty
  sentence once (“abuse takedowns and IP-reputation damage land on
  hardware and residential/office connections you cannot dispose of”)
  then the save proceeds. Honesty sentence only when the save includes
  `kind=ssh`. F8 seed+render that confirm. Tunnel-required refuse is a
  Finding, not a nag. Default dedicated cloud first.
- Reaper: plant orphaned partner site (Partner gone / kill-switched /
  quota-expired) → containers gone + routes detached. Distinct from
  Multipass and AWS purpose=test. Weekly drill writes
  `CheckRun.Kind.PARTNER_REAPER`.
- O1 (quote C12 fingerprints): partner-site hard-down P2 fingerprint
  `site-down:{name}`; N≥2 P1 fingerprint
  `partner-aggregate-down:{partner.pk}`; partner-tier host down P1
  reuses `host-down:{host}`; prod host-down / zone-down is **not**
  `partner-aggregate-down`. Pass `fingerprint=` explicitly (including
  the two global pins).
- K6 standing test from Task 4 must still fail if the **partner router**
  maps to these operator ids.
- Run-twice zero mutating calls.

**Exact req ids:** `PART-KILL-SWITCH`. Kill/rank chrome tests also mark
`UX-P55-PARTNERS`. Function-level `@pytest.mark.req` on the named tests
below. No live / skip-unless marker. Do not mark Q9 T3.

**Tests:**
- `test_partner_suspend_is_t1` — `PART-KILL-SWITCH`
- `test_partner_api_kill_switch_is_t1` — `PART-KILL-SWITCH`
- `test_enable_partner_api_is_t1_not_a_toggle` — `PART-KILL-SWITCH` + `UX-P55-PARTNERS`
- `test_global_flag_defaults_off` — `PART-KILL-SWITCH`
- `test_totp_does_not_satisfy_suspend` — `PART-KILL-SWITCH`
- `test_suspend_stops_containers_detaches_revokes` — `PART-KILL-SWITCH`
- `test_suspend_overlay_names_stop_detach_revoke` — `PART-KILL-SWITCH` + `UX-P55-PARTNERS`
- `test_site_takedown_is_t2_and_returns_410` — `PART-KILL-SWITCH`
- `test_takedown_control_is_on_partner_site_detail` — `PART-KILL-SWITCH` + `UX-P55-PARTNERS`
- `test_auto_trigger_files_partner_kill_switch_fingerprint` — `PART-KILL-SWITCH`
- `test_partner_reaper_plants_orphan_and_cleans` — `PART-KILL-SWITCH`
- `test_partner_reaper_writes_checkrun_kind_partner_reaper` — `PART-KILL-SWITCH`
- `test_multipass_and_aws_reapers_untouched`
- `test_partner_site_hard_down_fingerprint_is_site_down_name` — `PART-KILL-SWITCH`
- `test_n2_aggregate_fingerprint_is_partner_aggregate_down_partner_pk` — `PART-KILL-SWITCH`
- `test_partner_tier_host_down_reuses_host_down_fingerprint` — `PART-KILL-SWITCH`
- `test_prod_host_down_is_not_partner_aggregate_down` — `PART-KILL-SWITCH`
- `test_destination_rank_http_pin_and_own_server_honesty_sentence` — `UX-P55-PARTNERS`
- `test_destination_rank_own_server_is_t2_with_honesty_sentence` — `UX-P55-PARTNERS`
- `test_suspend_run_twice_zero_mutating_calls` — `PART-KILL-SWITCH`
- `test_partner_router_still_does_not_map_to_operator_ids`
- frontend F8: kill-switch overlay + destination-order confirm in
  `REQUIRED_STATE_IDS` and render on product screens — `UX-P55-PARTNERS`

**Dependencies:** Task 5 (append ACTION_TIERS after create). Task 1 for
schema / CheckRun kind.

---

## Task 8 — M2 git-webhook outbox type on the same poller

**Title:** `{type: "git-push"}` on the same Beat poller; Fake-planted;
zero Hub inbound; no public intake webhook route; no secret on intake.

**Files:** `monitor/intake_poll.py` (second message type; do not
`import intake`), `deploys/poller.py` (enqueue only — same seam `poll()`
already exposes), `intake/outbox.py` / `intake/fake.py` (plant helper
only — no new public route), `tests/test_git_webhook_outbox.py`, extend
`tests/test_git_poller.py` (inbound still 404), extend
`tests/test_intake_process.py` (public listener still six K3 families;
no webhook secret on intake).

**Do:**
- Outbox item `{type: "git-push", git_url, ref, sha}`. T1 Fake **plants**
  it (untrusted hint). No GitHub/Gitea/webhook HTTP listener on intake
  or Hub. Public intake listener remains the six K3 families. No
  webhook secret / `HUB_WEBHOOK_SECRET` / `GITHUB_WEBHOOK` / HMAC on
  intake.
- `git_url` through existing `validate_git_url`. Hub turns it into the
  existing git-poll enqueue. Same 10 s poller, same batch cap, same
  fail-closed client.
- Partner jobs remain `{type: "partner-job", ...}`. Unknown types refuse
  + AuditEvent.
- Hub gains **no** inbound webhook route. M2 404 standing tests stay green
  and still include `/api/partner` / `/mcp`.

**Exact req ids:** `PART-M2-GIT-WEBHOOK`, `PART-K1-ZERO-INBOUND-HUB`.
Function-level `@pytest.mark.req` on the named tests below. No live /
skip-unless marker.

**Tests:**
- `test_git_push_outbox_enqueues_deploy` — `PART-M2-GIT-WEBHOOK`
- `test_git_push_uses_same_poller_as_partner_job` — `PART-M2-GIT-WEBHOOK`
- `test_git_url_goes_through_validate_git_url` — `PART-M2-GIT-WEBHOOK`
- `test_git_push_is_fake_planted_not_a_public_route` — `PART-M2-GIT-WEBHOOK`
- `test_intake_public_listener_still_six_k3_routes` — `PART-M2-GIT-WEBHOOK`
- `test_intake_holds_no_webhook_secret` — `PART-M2-GIT-WEBHOOK`
- `test_unknown_outbox_type_refuses` — `PART-M2-GIT-WEBHOOK`
- `test_hub_still_has_no_webhook_or_partner_inbound` — `PART-K1-ZERO-INBOUND-HUB`
- `test_git_push_run_twice_zero_mutating_calls` — `PART-M2-GIT-WEBHOOK`

**Dependencies:** Task 3 (same poller). Do not edit `core/models.py`.

---

## Task 9 — U2 numbers in DECISIONS + quota tests

**Title:** Hub-authoritative quotas; Task 0 already copied D-084 numbers;
this task proves them and the fleet cap.

**Files:** `tests/test_partner_quotas.py`. Enforcement lives in the Task 4
re-validator — extend it if a knob is missing. Do **not** edit
`DECISIONS.md` (Task 0 owns it). Do not edit `core/models.py`.

**Do:**
- Hub refuses create-site when `Partner.objects.filter(pk=…).values` would
  exceed `max_sites` (default 5), fleet `PARTNER_FLEET_MAX_SITES` (12),
  `domains` (5), `deploys_per_day` (50). Rate: 60 req/min general;
  deploy-create 3/min + 100/day per site. Headers `X-RateLimit-*`.
- Intake saying allow cannot override Hub. Quota-abuse files fingerprint
  `budget-cap-hit:partner` (refs, never secrets). Unbounded `max_sites`
  (null / 0-as-infinite) refuses at clean()/create.
- Empty `INTAKE_URL` still does not green a live quota id (there is no
  live quota id). Task 3’s shared quota-exceeded vector remains the Q9
  pin; this task proves the U2 numbers.

**Exact req ids:** `PART-U2-QUOTAS`. Function-level `@pytest.mark.req` on
the named tests below. No live / skip-unless marker.

**Tests:**
- `test_max_sites_default_5` — `PART-U2-QUOTAS`
- `test_sixth_site_refuses` — `PART-U2-QUOTAS`
- `test_fleet_cap_12_refuses` — `PART-U2-QUOTAS`
- `test_deploys_per_day_default_50` — `PART-U2-QUOTAS`
- `test_domains_default_5` — `PART-U2-QUOTAS`
- `test_hub_refuses_even_if_intake_says_allow` — `PART-U2-QUOTAS`
- `test_unbounded_max_sites_refused` — `PART-U2-QUOTAS`
- `test_quota_abuse_files_budget_cap_hit_partner` — `PART-U2-QUOTAS`
- `test_rate_limit_60_and_deploy_create_3_per_min` — `PART-U2-QUOTAS`
- `test_d084_numbers_match_partner_field_defaults` — `PART-U2-QUOTAS`

**Dependencies:** Task 0 + Task 1 + Task 4. Do not edit `core/models.py`.

---

## Task 10 — SLIP: HMAC/bearer evaluation writeup (does not block MUST demo)

**Title:** Written evaluation only. Ed25519 stays. Do not enable HMAC.

**Files:** `docs/hmac-bearer-evaluation.md` (same shape as
`docs/ssh-ca-evaluation.md` / `docs/yubikey-kek-rung-2-evaluation.md`).

**Do:**
- Evaluate HMAC/bearer vs Ed25519 (§K2). Decide **not** to enable this
  phase. Record what would reverse it (a named partner who cannot sign,
  plus Hub-side-only secret + verify).
- Do not add an HMAC secret to the vault. Do not change
  `intake/verify.py` or `core/partner_verify.py`.
- Do not register a phase-5.5 due id that this writeup would have to mark.
- MUST demo does not wait.

**Exact req ids:** none.

**Tests:** none required. Existing Ed25519 vector tests stay green.

**Dependencies:** none for the writeup. MUST demo does not wait.

---

## Task 11 — Acceptance + demo

**Title:** `tests/acceptance/test_phase_5_5.py` +
`conformance/demos/phase-5.5.md`

**Files:** those two. `@pytest.mark.acceptance(phase=5.5)` on the module
(acceptance mark, not a MUST `@pytest.mark.req`). Demo record is
non-empty and names the MUST path in design note §4. Do not claim a
named committed partner. Do not claim live intake / CF-for-SaaS. Do not
claim HMAC enablement. Do not claim MCP. Do **not** create
`conformance/demos/named-partner.md`.

**Exact req ids:** `P55-PARTNER-DEMO` (`verify: demo` — the file, not a
pytest marker). `PART-U1-NAMED-PARTNER` stays uncovered (due on
`conformance-5.5` only). Everyday `review-round` (phase 5) may go green
while U1 is uncovered. Two consecutive clean `conformance-5.5` rounds
wait on Joseph.

**Named acceptance nodeids** (one per §4 beat;
`tests/acceptance/test_phase_5_5.py::`):
- `test_empty_partners_tab_is_create_partner_never_connected`
- `test_partner_create_t1_201_returns_hubk_and_whsec_once`
- `test_get_never_echoes_hubk_or_whsec`
- `test_global_flag_defaults_off`
- `test_enable_is_t1_not_a_toggle`
- `test_signed_create_site_on_intake_not_hub`
- `test_hub_reverify_rejects_replay_even_if_intake_forwards`
- `test_idempotency_match_and_mismatch_422`
- `test_partnersite_isolation_no_site_tier`
- `test_dockerfile_git_source_refuses`
- `test_partner_a_404s_on_b`
- `test_hub_host_and_cohost_refuse`
- `test_custom_hostname_txt_before_serve`
- `test_webhooks_fake_sink_standard_webhooks`
- `test_suspend_t1_stop_detach_revoke`
- `test_takedown_t2_410_on_site_detail`
- `test_destination_rank_own_server_honesty_sentence`
- `test_partner_reaper_vs_multipass_and_aws`
- `test_partner_site_hard_down_p2_not_prod_p1`
- `test_git_push_outbox_on_same_poller`
- `test_quotas_max_sites_5_fleet_12`
- `test_empty_intake_url_skips_without_checkrun_flood`
- `test_nav_stays_six`
- `test_demo_does_not_claim_named_partner_or_live_intake`

Pin a `NAMED` tuple of those function names in the acceptance module
(phase-5 shape). `VALID_TIERS` stays `{t1, t2, t3}`.

**Dependencies:** Tasks 1–9 (not 10).
