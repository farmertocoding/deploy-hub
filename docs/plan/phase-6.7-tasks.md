# Phase 6.7 tasks — T1 Fake overflow enroll (propose-gated)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** T1 `instance.create` with `overflow_site` enrolls an ephemeral Target via FakeCloudProvider only when overflow is ACCEPTED and idle pick missed; OPEN/ACKED/idle/attack refuse; evaluator still never creates a Target.

**Architecture:** `provision/overflow.py::enroll_overflow_target` calls `refuse_if_attack`, requires ACCEPTED `scale-out-proposal:{pk}`, then `pick_overflow_home` (hit refuses), then `enroll_aws_target(..., instance_type=t3.medium)`. `InstanceCreateView` branches on optional `overflow_site`. `scaling/` does not import `provision`.

**Tech Stack:** Django, pytest T1 FakeCloudProvider, existing `instance.create` T1.

**Spec:** `docs/phase-6.7-design-note.md` **r2** (panel §7 is binding). Do not start implementation until design panel MERGE on r2. Do not invent a path, env, Finding fingerprint, action id, or gate shape that §7 does not name.

**Branch:** work in place (goal harness). Do not push. Do not merge without the panel.

## Global Constraints

- Secrets through the vault. Spec tag `overflow_site` is the integer pk only. Never copy `collect_payload` / `ssh_key_ref` / AWS keys into Finding, AuditEvent.detail, or spec tags.
- **Do not invent** `HUB_TEST_CF_TOKEN` / `HUB_TEST_AWS_TOKEN` / `HUB_TEST_PARTNER_TOKEN` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`.
- **`0014` is closed.** No Hub migration. No `ScalePolicy`. No overflow FK. No SiteInstance write.
- Fingerprints unchanged. `evaluate_site` **must not** call enroll. AST-scan `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` unchanged from 6.6.
- Do not add `scale.approve` or `overflow.enroll` to ACTION_TIERS. Reuse `instance.create` (T1).
- Overflow tests inject `FakeCloudProvider` + FakeTransport (see `tests/test_aws_enroll.py`). Do not call live `cloud_provider_for` in those tests.
- `refuse_if_attack` first on the overflow enroll path. Do not mock `refuse_if_attack`, `pick_overflow_home`, or `evaluate_site`.
- Reviewer never writes the code they review (D-014).
- New MUST ids are phase 6, tier-less. No `t4`. Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. Do not waive U1 / PART-K / `failed` / `not-collected`. Do not stub `named-partner.md`.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` except Task 0.
- Copy never says “instance” except `single-instance` / `single-instance-only` in Finding/UI copy. Existing `instance.create` action id and URL stay.
- **Markers:** function-level `@pytest.mark.req` on `def test_*` only. Do not `@pytest.mark.req("P6-SCALER-DEMO")`. Do not mark existing no-`overflow_site` create tests with `SCALE-OVERFLOW-T1-ENROLL`.
- TDD: failing test first. Long "why" HEREDOC commits; no amend.
- Do not edit `evaluate_all` / `CYCLE_LOCK*` / `monitor/tasks.py` / `hub/settings/base.py` / `scaling/evaluator.py` product (AST tests may stay).

Protective cut (**D-104**): MUST = Tasks 0–2.

## Parallel waves

| Shared file | Order |
|---|---|
| registry / DECISIONS / paths / CODEOWNERS / PHASE_6_MUST_IDS | Task 0 |
| `provision/overflow.py` / `core/views.py` InstanceCreateSerializer | Task 1 after 0 |
| acceptance + demo | Task 2 after 1 |

---

### Task 0: Registry + custody (D-104…D-106)

**Files:** `DECISIONS.md`, `conformance/requirements.yaml`, `conformance/paths.yaml`, `.github/CODEOWNERS`, `tests/test_conformance_gate.py`

- [ ] **Step 1: Failing tests** — extend `PHASE_6_MUST_IDS` with `SCALE-OVERFLOW-T1-ENROLL`; add `phase-6.7-design-note.md §3` to `allowed_sources`; assert `provision/overflow.py` in paths.yaml and CODEOWNERS (unmarked custody). Do not rewrite `SCALE-PROPOSE-NO-PROVISION` `text:`.

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — copy D-104…D-106 from design note §5. Add the new id `phase: 6`, `verify: test`, no `tier:`, `source: phase-6.7-design-note.md §3`; compute `text_hash:` via `python conformance/check.py --print-text-hashes`. Claim `provision/overflow.py` in **both** paths.yaml and CODEOWNERS. No MUST waiver.
- [ ] **Step 4: PASS** `pytest tests/test_conformance_gate.py::test_phase_6_due_set_includes_all_section_3_must_ids tests/test_d023_actions_not_required.py tests/test_proc_rules.py -q`
- [ ] **Step 5: Commit** long why HEREDOC. No amend.

---

### Task 1: `enroll_overflow_target` + serializer branch

**Files:** create `provision/overflow.py`; modify `core/views.py` (`InstanceCreateSerializer`, `InstanceCreateView.post`); tests in `tests/test_overflow_enroll.py` (create). Reuse `_t1_user` / `_touch` / RecordingCloud / FakeTransport from `tests/test_aws_enroll.py`. Reuse `_ready_site` / `_overflow_after_cheap` / `_plant` from `tests/test_scale_evaluator.py`.

- [ ] **Step 1: Failing tests** in `tests/test_overflow_enroll.py`

```python
CREATE_URL = "/api/v1/instance/create/"
FIX = "Ack is not launch. Propose-mode does not launch."


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_accepted_overflow_t1_create_enrolls_ephemeral_via_fake():
    # ACCEPTED overflow, no idle machine, FakeCloudProvider injected
    # POST overflow_site + confirm_name == host + T1 touch
    # 201; Target.kind aws_ec2; lifecycle ephemeral; count +1
    # provider.create_instance called with instance_type t3.medium


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_open_overflow_refuses_with_ack_is_not_launch():
    # OPEN overflow + T1 POST overflow_site → 4xx; detail exact FIX; count unchanged
    # Finding count and CheckRun count unchanged; create_instance not called


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_acked_overflow_refuses_with_ack_is_not_launch():
    # ACKED (not ACCEPTED) → 4xx; FIX; count unchanged


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_idle_registered_machine_refuses_overflow_enroll():
    # ACCEPTED overflow + second READY permanent ram=10 at now
    # → 4xx; count unchanged; no create_instance


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_attack_refuses_overflow_enroll():
    # ACCEPTED overflow + attack playbook engaged → 4xx; count unchanged


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_overflow_enroll_still_requires_recent_touch():
    # ACCEPTED overflow, no touch → 403; count unchanged


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_overflow_enroll_still_requires_type_the_name():
    # ACCEPTED overflow, touch, confirm_name != host, overflow_site set → 400
    # count unchanged; create_instance not called


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_missing_overflow_finding_refuses():
    # no scale-out-proposal:{pk} row; T1 POST overflow_site → 4xx; FIX; count unchanged


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_resolved_overflow_refuses_with_ack_is_not_launch():
    # RESOLVED row → 4xx; FIX; count unchanged; create_instance not called


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_partner_site_refuses_overflow_enroll():
    # PartnerSite bound, ACCEPTED overflow planted, playbook quiet → 4xx; count unchanged


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
@pytest.mark.req("SCALE-PROPOSE-NO-PROVISION")
def test_evaluate_site_still_does_not_create_a_target():
    # AST scaling/ + monitor/tasks.py + monitor/host_metrics.py forbids 6.6 list
    # AND enroll_overflow_target / provision.overflow
    # evaluate_site on ACCEPTED cheap+overflow does not +1 Target
    # Do not rewrite SCALE-PROPOSE-NO-PROVISION text


def test_create_without_overflow_site_unchanged():
    # unmarked: existing instance.create without overflow_site still 201 via Fake
```

- [ ] **Step 2: RED**
HTTP inject helper (every overflow POST, including refuse): `RecordingCloud` + `FakeTransport`; wrap real `enroll_overflow_target` with `kwargs.setdefault("provider", ...)` / `make_transport`; patch the **module attribute the view calls** (`provision.overflow.enroll_overflow_target`). Happy path: `create_instance` called with `instance_type=t3.medium` and tags `overflow_site` equal to the integer Site pk (int or `str(pk)`); spec/kwargs/tags contain no `collect_payload` / `ssh_key_ref` / `private_key` / `ssh_private_key` / AWS access-key material. Refuse paths: `create_instance` not called; Finding count and CheckRun count unchanged.

- [ ] **Step 3: GREEN** — C2/C3/C4. `provision/overflow.py` as §2. Views branch after confirm_name. Inject Fake in tests. No schema. No Beat. No ACTION_TIERS row. Gate EnrollError does not write Finding/CheckRun.
- [ ] **Step 4: PASS** `pytest tests/test_overflow_enroll.py tests/test_aws_enroll.py tests/test_overflow_destination.py tests/test_scale_evaluator.py -q`
- [ ] **Step 5: Commit** long why HEREDOC. No amend.

---

### Task 2: Acceptance + demo append

**Files:** `tests/acceptance/test_phase_6.py`, `conformance/demos/phase-6.md`

- [ ] **Step 1:** Add `test_accepted_overflow_t1_enrolls_ephemeral_via_fake` to `NAMED`. Docstring transcribes §4. Body imports (`from test_overflow_enroll import ...`) and **calls** (do not reimplement): `test_accepted_overflow_t1_create_enrolls_ephemeral_via_fake`, `test_open_overflow_refuses_with_ack_is_not_launch`, `test_idle_registered_machine_refuses_overflow_enroll`, `test_attack_refuses_overflow_enroll`. Mark `SCALE-OVERFLOW-T1-ENROLL`. Do not mark `P6-SCALER-DEMO`. Keep §4 6.6 idle/t3 NAMED tests.

- [ ] **Step 2: RED** (demo nodeid missing)
- [ ] **Step 3: Append** `conformance/demos/phase-6.md` with the T1 Fake enroll clause and the new nodeid. Honest: no live AWS VM, no DNS join, no auto, no AMI.
- [ ] **Step 4: PASS** acceptance + overflow enroll + evaluator. `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3` — new id verified; U1 uncovered-only allowed.
- [ ] **Step 5: Commit** long why HEREDOC. No amend.
