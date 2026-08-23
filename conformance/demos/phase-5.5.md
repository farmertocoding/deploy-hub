# Phase 5.5 exit demo — recorded (P55-PARTNER-DEMO)

**Date:** 2026-08-24 · **Branch:** `p55-t11` · **Recorded by:** Task 11
on BASE `36c5162` (merge of MUST Tasks 0–9, plus Task 10 HMAC/bearer
evaluation writeup) plus the acceptance / demo files in this change.
**T1 fakes only.** This is not a live intake, live Cloudflare-for-SaaS,
named committed partner, HMAC enablement, MCP, or Playwright success.
No new token env was added. Pinned env remains `INTAKE_URL` /
`PARTNER_API_ENABLED` / `PARTNER_FLEET_MAX_SITES`. `HUB_TEST_ZONE_SLUGS`
remains the DNS allowlist.

## What the milestone asked (design note §4)

Settings Partners tab: empty tab is one sentence + T1 **Create partner**
(not Connect); Fake / empty `INTAKE_URL` / post-create never paints
`Connected` (name the Fake). T1 `partner.create` requires WebAuthn touch
+ type-the-name (confirm = slug), mints Ed25519, **201 returns**
`hubk_test_` + `whsec_` **once**; GET / list / AuditEvent / Finding /
CheckRun / log never echo them; private key is not a Partner column and
is not vaulted. Global partner-API flag is OFF until T1
`partner.api_kill_switch` enables it (label “Enable partner API”, type
`partner-api` — never a toggle) → signed `POST /partner/v1/sites` on the
**intake** (in-process Fake) with Idempotency-Key lands in the mesh
outbox; Hub Beat (10 s, `probes`) pulls, **re-verifies** Ed25519 from the
shared vector file, rejects expired / mutated-body / replay **even when
the Fake intake forwards**, stores first response 24 h, mismatch 422 →
validated job becomes an ordinary Deployment on a dedicated destination
Target via `PartnerSite` (no `Site.tier` / `Site.partner_id` /
`Target.tier`); partner Dockerfile / git-source / unconstrained image
refuses; partner A 404s on B’s ids; Hub host and non-partner co-host
refuse → Settings Partners ranker: ranking `kind=ssh` is T2
`POST /api/v1/partners/<pk>/destination-rank/` with ConfirmDialog
`summary` = the K5 honesty sentence once → Fake CustomHostname
(capability on the `dns_provider_for` object) is not served until TXT
verifies; Standard Webhooks Hub-egress re-resolves at every delivery,
signs vs a reference verifier against a Fake sink; `whsec_` is vault-only
→ T1 `partner.suspend` overlay names stop containers / detach routes /
revoke the Hub-side key; per-site takedown is T2 on partner site detail
(`{domain} route → 410`) → 410; reaper weekly drill plants an orphaned
partner site and writes `CheckRun.Kind.PARTNER_REAPER`; Multipass and AWS
purpose=test reapers stay → partner-site hard-down is P2 fingerprint
`site-down:{name}`; N≥2 is P1 fingerprint
`partner-aggregate-down:{partner.pk}`; partner-tier host down reuses
`host-down:{host}`; prod host-down is not `partner-aggregate-down` →
git-webhook outbox type on the **same** poller is Fake-planted
`{type: "git-push"}` with zero Hub/intake inbound listener → quotas:
fifth site over `max_sites=5` refuses; fleet cap 12 refuses; empty
`INTAKE_URL` SKIPPED not P1 and does not grow CheckRun every 10 s → NAV
is still six.

Record: `conformance/demos/phase-5.5.md`. This record **does not claim a
named** committed partner and **does not claim live intake**.
`PART-U1-NAMED-PARTNER` stays uncovered until Joseph writes
`conformance/demos/named-partner.md`. Everyday `make review-round`
(phase 5) may go green while U1 is uncovered. Two consecutive clean
`make conformance-5.5` rounds wait on that interrupt; this session did
not run them. `make conformance-5.5` is the phase gate and **excludes
t2/t3**. Live intake / CF-for-SaaS stay skipped-only, never a T1-sibling
green. No invented token env. No paid edge.

## The honest state of this host

T1. Fakes actually driven this session:

- `FakeIntake` (in-process WSGI intake; six K3 public families; plant helper)
- `FakeIntakeClient` (Hub poller; fail-closed constructor; injected, not bound)
- `FakeHelper` (django-otp-webauthn protocol; T1 touch on create / enable / suspend)
- `FakeTransport` (suspend stop+detach; partner reaper plant/clean)
- `FakeWebhookSink` (Standard Webhooks reference verify; no live POST)
- `FakeDnsProvider` (custom_hostname capability; TXT-before-serve)

`INTAKE_URL` defaults empty. `PARTNER_API_ENABLED` defaults False.
`HUB_TEST_MODE` is off unless a test flips it. No Playwright. Multipass
is not part of this record. No live intake process was bound. No named
committed partner was supplied.

## What actually landed (Tasks 0–9, T1)

This session re-ran the marked T1 source files on `ff14847` before the
record file: **126 passed**, 0 skipped, across
`test_partner_create.py`, `test_partner_kill_switch.py`,
`test_intake_process.py`, `test_partner_verify.py`,
`test_intake_poll.py`, `test_partner_isolation.py`,
`test_custom_hostname.py`, `test_partner_webhooks.py`,
`test_partner_reaper.py`, `test_partner_o1.py`,
`test_git_webhook_outbox.py`, `test_partner_quotas.py`,
`test_partner_k6.py`,
`test_conformance_gate.py::test_valid_tiers_still_t1_t2_t3_only`,
`test_conformance_gate.py::test_p55_partner_demo_names_phase_5_5_md`,
`test_conformance_gate.py::test_part_u1_names_named_partner_md_and_file_is_absent`,
`test_makefile_nightly.py::test_conformance_5_5_is_phase_5_5_minus_live_tiers`,
`test_makefile_nightly.py::test_conformance_5_5_is_not_a_review_round_or_nightly_prereq`,
`test_makefile_nightly.py::test_review_round_conformance_is_phase_5_minus_live_tiers`.
Then the named acceptance file was written and its twenty-two behavioural
clauses passed on those same fakes; the two record clauses stayed red
until this file existed. After this file:
`tests/acceptance/test_phase_5_5.py` is expected **24 passed**, 0 skipped
(T1 fakes).

### Settings Partners tab

Empty GET `/api/v1/partners/` returns `intake.status=degraded`,
`intake.mode=fake`, `configured=false`, never `\bConnected\b`. The
Partners panel copy is **Create partner**, not Connect. Post-create with
empty `INTAKE_URL` still names the Fake and never Connected.

### T1 create + secrets once

`partner.create` is T1 (RequireRecentTouch HTTP + type-the-name; confirm
= slug). Under `HUB_TEST_MODE`, 201 returns `hubk_test_` + `whsec_` once.
GET list and GET detail never echo those prefixes. The Ed25519 private
key is not a Partner column and is not vaulted. `whsec_` is
`Secret.Kind.WEBHOOK_SECRET` under `owner_type="partner"`.

### Global flag + enable

`PARTNER_API_ENABLED` defaults False; prod.py does not assign it on.
Enable is the same T1 id with chrome label “Enable partner API” when OFF
(type `partner-api`), never a checkbox or switch.

### Signed create on intake, not Hub

Signed `POST /partner/v1/sites` against in-process `FakeIntake` returns
201 and lands a `partner-job` on the mesh outbox. Unsigned POST is not
201. Hub urlpatterns contain neither `/api/partner` nor `/mcp`; candidate
paths 404.

### Hub re-verify, replay, idempotency

Shared `conformance/fixtures/partner-signature-vectors.json` passes both
verifiers on valid. Replay is rejected at Hub even when Fake intake
forwards; C12 fingerprint is `partner-replay:{partner.pk}`. Idempotency
match returns the first response; param mismatch is 422.

### Isolation + templates

No `Site.tier`, no `Site.partner_id`, no `Target.tier`. Partner A 404s on
B’s ids. Hub host and non-partner co-host refuse. Dockerfile / git-source
/ unconstrained image refuse.

### CustomHostname + webhooks

`FakeDnsProvider(custom_hostname=True)` does not serve until TXT
ownership is upserted. Helpers in `providers/custom_hostname.py` do not
construct a Cloudflare client and contain no ACME / DNS-01.
`FakeWebhookSink` deliveries verify with the Standard Webhooks reference
library. Delivery re-resolves and refuses a rebind to 169.254.169.254.
`whsec_` is not on intake.

### Kill switch + rank + reaper + O1

T1 suspend: Fake Transport `docker stop` + Caddy DELETE + pubkey cleared.
T2 takedown on partner site detail returns 410. Destination rank of
`kind=ssh` is T2 and carries the K5 honesty sentence once; own-server
without tunnel files a Finding. Partner reaper plants orphan
(partner-gone / kill-switched / quota-expired), stops + detaches, writes
`CheckRun.Kind.PARTNER_REAPER`. Multipass stays `hub-t3-`; AWS stays
`purpose=test`. Partner-site hard-down is P2 `site-down:{name}`; N≥2 is
P1 `partner-aggregate-down:{partner.pk}`; prod host-down is not
`partner-aggregate-down`.

### Git-push outbox + quotas + empty URL + NAV

Fake-planted `{type: "git-push"}` uses the same 10 s `poll-intake-outbox`
Beat entry; public intake listener is still the six K3 families. Hub
enforces `max_sites=5` and fleet cap 12. Empty `INTAKE_URL` is SKIPPED
with zero `CheckRun.Kind.INTAKE_POLL` rows. NAV is the six objects.
`VALID_TIERS` stays `{t1, t2, t3}`.

## Still outstanding — named, not greened

- `PART-U1-NAMED-PARTNER` stays uncovered. `conformance/demos/named-partner.md`
  is absent. This record does not claim a named committed partner. T1
  fixture slugs are not that proof.
- Live intake / live CF-for-SaaS / `api.partners.<domain>` are Joseph
  interrupts. This record is **not a live intake**. No live CustomHostname
  SaaS path was driven.
- HMAC/bearer is evaluation outstanding (`docs/hmac-bearer-evaluation.md`,
  Task 10). This record does not enable HMAC; it does not claim HMAC
  enablement. Ed25519 stays.
- MCP is OUT (not a slip). This record does not claim MCP.
- Two consecutive clean `conformance-5.5` rounds wait on the Joseph
  interrupt. This session did not run `make review-round` or
  `make conformance-5.5`; those gates re-earn green from a fresh
  run-report.
- T4 Playwright is out of scope. No Playwright.
- Q9 T2 container and Q9 T3 live path stay skip-unless the existing
  test-plane wall; T1 Fake tests do not mark those ids.

## Acceptance transcription — real nodeids

`tests/acceptance/test_phase_5_5.py` (`@pytest.mark.acceptance(phase=5.5)`),
T1 fakes, this session:

- `::test_empty_partners_tab_is_create_partner_never_connected`
- `::test_partner_create_t1_201_returns_hubk_and_whsec_once`
- `::test_get_never_echoes_hubk_or_whsec`
- `::test_global_flag_defaults_off`
- `::test_enable_is_t1_not_a_toggle`
- `::test_signed_create_site_on_intake_not_hub`
- `::test_hub_reverify_rejects_replay_even_if_intake_forwards`
- `::test_idempotency_match_and_mismatch_422`
- `::test_partnersite_isolation_no_site_tier`
- `::test_dockerfile_git_source_refuses`
- `::test_partner_a_404s_on_b`
- `::test_hub_host_and_cohost_refuse`
- `::test_custom_hostname_txt_before_serve`
- `::test_webhooks_fake_sink_standard_webhooks`
- `::test_suspend_t1_stop_detach_revoke`
- `::test_takedown_t2_410_on_site_detail`
- `::test_destination_rank_own_server_honesty_sentence`
- `::test_partner_reaper_vs_multipass_and_aws`
- `::test_partner_site_hard_down_p2_not_prod_p1`
- `::test_git_push_outbox_on_same_poller`
- `::test_quotas_max_sites_5_fleet_12`
- `::test_empty_intake_url_skips_without_checkrun_flood`
- `::test_nav_stays_six`
- `::test_demo_does_not_claim_named_partner_or_live_intake`

No `@pytest.mark.req` on `P55-PARTNER-DEMO` (verify: demo is this file).
No MUST id marked on a skip-unless or live test.

## Gates

`conformance-5.5` = `python conformance/check.py --phase 5.5 --exclude-tier t2 --exclude-tier t3`.
Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`.
`conformance-5` stays phase 5 minus live. `conformance-3` stays all-tiers
Phase 3. New phase-5.5 MUST ids are tier-less. `VALID_TIERS` is
`{t1, t2, t3}` — t4 was not added. `conformance-5.5` is not a
`review-round` or `nightly-gates` prereq. The proofs this file records
are the T1 pytest nodeids above.
