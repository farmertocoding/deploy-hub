# Phase 6 exit demo — recorded (P6-SCALER-DEMO)

**Date:** 2026-08-25 · **Branch:** `p6-design` · **Recorded by:** Task 6
on BASE `fe8e20e` (merge of MUST Tasks 0–5) plus the acceptance file
`2fdab81` and this record. Phase 6.6 Task 2 appended the idle-first
clause on HEAD `f6824e9`. **T1 fakes only.** This is not a live AWS,
live provision, live Cloudflare, named committed partner, or Playwright
success. No VM launched. No auto mode. No AMI. No ScalePolicy table.
No DNS join. No new token env was added.

## What the milestone asked (design note §4)

A public scale-ready site (`core.scale-ready` ok, `Site.scale_ready=True`,
not `mesh_only`), quiet attack playbook, not a PartnerSite, five
HostMetric rows `ram=90` one distinct UTC minute apart inside the 300s
window → Findings inbox shows P2 **scale-out-proposal** fingerprint
`scale-out-proposal:{pk}`; `fix_action` is the C8 sentence; Target
count unchanged; no `enroll_aws_target` call. (a) No other ready Target
with headroom → body contains `0.0416` / `t3.medium`. (b) A second
READY permanent non-hub Target with a latest ram=10 sample at `now` →
body contains `idle registered machine`, that host, `0`, `own-machine`,
`propose-mode does not launch`; Target count unchanged; no enroll. No
VM launched. No ScalePolicy. No DNS join. Re-evaluate while OPEN
does not add a push-log event. Four of five over + one under → no
Finding. One spike → no Finding. Disk-only five hot minutes → no
Finding. Same pressure while attack playbook is engaged
(`FakeEdgeProtection`) → no `scale-out-proposal` (attack Finding may
exist); an already-OPEN proposal is resolved. Same pressure on a
PartnerSite → no proposal. A site with `scale_ready=False` and five hot
mem samples → no proposal; Sites **list** paints **single-instance-only**.
`mesh_only` + five hot mem → no proposal. NAV is still six.

Record: `conformance/demos/phase-6.md`. This record **does not claim a
VM launched**, auto mode, AMI, live AWS, live provision, DNS join,
ScalePolicy, or U1.
`PART-U1-NAMED-PARTNER` stays uncovered until Joseph writes
`conformance/demos/named-partner.md`. Everyday `make review-round`
(phase 5) may go green while U1 is uncovered. Two consecutive clean
`make conformance-6` rounds close the phase; this session did not run
them. `make conformance-6` is the phase gate and **excludes t2/t3**:
`python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3`.
Live AWS stays skipped-only, never a T1-sibling green. No invented token
env. No paid AWS.

## The honest state of this host

T1. Fakes actually driven this session:

- `FakeEdgeProtection` (L5 playbook engaged; `refuse_if_attack` first;
  OPEN/ACKED proposal system-resolved; no scale-out-proposal filed)

HostMetric rows are real Django rows (Hub-clock `ts`, ram=90), not a
fake metric port. Partner refuse binds a real `PartnerSite`. Attack
refuse drives `FakeEdgeProtection` then `run()`. `AWS_CREDENTIALS_REF`
defaults empty. `HUB_TEST_MODE` is off unless a test flips it. No
Playwright. Multipass is not part of this record. No live AWS. No live
provision. No VM launched.

## What actually landed (Tasks 0–5, T1)

This session re-ran the marked T1 source files on `fe8e20e` before the
record file: **41 passed**, 0 skipped, across
`test_scale_evaluator.py`, `test_scale_ready_scan.py`,
`test_sites_single_instance.py`. Then the named acceptance file was
written and its six behavioural clauses passed on those same fakes; the
two record clauses stayed red until this file existed. After this file:
`tests/acceptance/test_phase_6.py` was **8 passed**, 0 skipped (T1
fakes). Phase 6.6 Task 2 adds §4 (b); the file is expected **9 passed**,
0 skipped.

### Sustained propose (quiet, scale-ready, public)

Five distinct UTC minutes of `ram=90` inside the 300s Hub-clock window
file kind `scale-cheap-remediation` first (`scale-cheap-remediation:{site.pk}`),
body names Cache-Control / Cloudflare cache / gunicorn 2×CPU+1, then
accept-risk of that row files kind `scale-out-proposal` fingerprint `scale-out-proposal:{site.pk}`
P2, title `Scale-out proposal awaiting approval (propose mode)`,
`fix_action` exactly `Ack is not launch. Propose-mode does not launch.`,
body names the site, `ram`, `0.0416`, `t3.medium`, and
`propose-mode does not launch`. Entity is `site:{domain}`, not pk.
Target count is unchanged. AST-scan of `scaling/` + `monitor/tasks.py` +
`monitor/host_metrics.py` finds no `provision.aws_enroll`, `providers.ec2`,
`enroll_aws_target`, `InstanceCreateView`, `boto3`, or `CloudProvider`.
Re-evaluate while OPEN returns the same row and does not add a push-log
event. Same-axis `load>cores` also files. Disk-only five hot minutes do
not file.

### Idle registered machine before t3.medium (§4 (b), Phase 6.6)

Same public scale-ready quiet site, five ram=90 minutes, ACCEPTED cheap
→ overflow. (a) stays the no-second-Target path: body names `0.0416` /
`t3.medium`; Target count unchanged
(`test_scale_ready_quiet_five_hot_mem_files_p2_proposal`). (b) A second
READY permanent non-hub Target with a latest ram=10 sample at `now`:
body names `idle registered machine`, that host, `Overflow estimate 0
USD/hour on own-machine`, and `propose-mode does not launch`; Target
count unchanged; no enroll. No `\bApprove\b` / `\bLaunch\b`. This
session did not launch a VM, did not add a ScalePolicy table, and did
not join DNS. F8 `scale-out-proposal` seed stays the no-idle `0.0416` /
`t3.medium` case. Propose-mode still does not create a Target.

### Four-of-five / spike / hole / mixed / stale

Four of five in-window minutes over + one under does not file. A single
newest ram=90 among four cold minutes does not file. A missing UTC
minute, mixed ram/load axes, or five hot rows older than the 300s
window do not file.

### Attack + partner refuse

`evaluate_site` calls `refuse_if_attack` first. `FakeEdgeProtection` +
`run()` with attack-shaped traffic files no `scale-out-proposal:{pk}`;
an already-OPEN proposal is system-resolved (`source="system"`). A
`PartnerSite` with a quiet playbook and five hot mem does not file;
binding `PartnerSite` after file system-resolves the OPEN proposal.

### Scale-ready + Sites list + NAV

`core.scale-ready` is warning, never blocker. `Site.scale_ready` defaults
False; missing check or warning is False even if `confirm_warnings`.
`scale_ready=False` + five hot mem does not propose. `mesh_only` + five
hot mem does not propose. Live project rows emit `scale_ready` as a real
bool and do not alias `single_instance = not scale_ready`. `SiteObserved`
on Sites **list** rows paints **single-instance-only** iff
`scale_ready === false`. F8 required states `single-instance-only` and
`scale-out-proposal`. The proposal Finding has no Approve or Launch
control. NAV is the six objects. `VALID_TIERS` stays `{t1, t2, t3}`.

## Still outstanding — named, not greened

- `PART-U1-NAMED-PARTNER` stays uncovered. `conformance/demos/named-partner.md`
  is absent. This record does not claim a named committed partner.
- PART-K text and `text_hash` stay the 4f30c7a freeze. This record does
  not rewrite them.
- Live AWS of any kind is a Joseph interrupt. This record does not claim
  live provision, auto mode, AMI, a ScalePolicy table, or a DNS join.
- Two consecutive clean `conformance-6` rounds wait on the U1 interrupt.
  This session did not run `make review-round` or two consecutive
  `make conformance-6` rounds; those gates re-earn green from a fresh
  run-report.
- T4 Playwright is out of scope. No Playwright.
- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2
  --exclude-tier t3`. `conformance-6` is not a `review-round` or
  `nightly-gates` prereq.

## Acceptance transcription — real nodeids

`tests/acceptance/test_phase_6.py` (`@pytest.mark.acceptance(phase=6)`),
T1 fakes, this session:

- `::test_scale_ready_quiet_five_hot_mem_files_p2_proposal`
- `::test_idle_registered_machine_named_when_second_target_has_headroom`
- `::test_four_of_five_does_not_propose`
- `::test_one_spike_does_not_propose`
- `::test_attack_engaged_does_not_propose`
- `::test_partner_site_does_not_propose`
- `::test_not_scale_ready_does_not_propose_and_list_paints_single_instance_only`
- `::test_nav_stays_six`
- `::test_demo_does_not_claim_live_provision_or_auto_or_ami`

No `@pytest.mark.req` on `P6-SCALER-DEMO` (verify: demo is this file).
No MUST id marked on a skip-unless or live test.

## Gates

`conformance-6` = `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3`.
Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`.
`conformance-5` stays phase 5 minus live. `conformance-3` stays all-tiers
Phase 3. New phase-6 MUST ids are tier-less. `VALID_TIERS` is
`{t1, t2, t3}` — t4 was not added. `conformance-6` is not a
`review-round` or `nightly-gates` prereq. The proofs this file records
are the T1 pytest nodeids above.
