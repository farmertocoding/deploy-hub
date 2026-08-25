# Phase 6.9 tasks — Join overflow traffic (T1 Fake DNS; tunnel replica sibling)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `join_overflow_traffic` upserts the overflow A next to the primary (round-robin, `proxied=site.proxied`) without retargeting `primary_target`; tunnel-mode home sites call an injected replica instead of an A record; OPEN/ACKED refuse with Ack is not launch.

**Architecture:** `deploys/overflow.py` owns the gate + join. DNS path reuses `ensure_dns`. `_assemble_desired` rewrites `dns_values` **and** `dns_set` from the comma-joined `DnsRecord` so the next primary deploy cannot drop the overflow origin. T1 POST `/api/v1/sites/{pk}/overflow-join/`. Tests inject `FakeDnsProvider`.

**Spec:** `docs/phase-6.9-design-note.md` **r2**. Do not start implementation until design panel MERGE on r2. Do not invent a path/env/fingerprint/action/gate that §7 does not name.

**Branch:** work in place. Do not push. Do not merge without the panel.

## Global Constraints

- Secrets through the vault. No `collect_payload` / SSH private keys / AWS keys / tunnel JWT in Finding, AuditEvent.detail, task kwargs, or artifacts.
- **Do not invent** `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.
- **`0014` is closed.** No overflow FK. Do not assign `Site.primary_target`.
- `evaluate_site` never joins traffic. `enroll_overflow_target` / `deploy_overflow_copy` do not call join. AST 6.8 banned list plus `join_overflow_traffic`.
- Do not add `scale.approve`. New ACTION_TIERS id is exactly `site.overflow_join` T1. Label exactly `Join overflow traffic`.
- Join tests inject `FakeDnsProvider`. Do not live-DNS. Do not `CloudProvider.get_instance`. Do not `vault.service.get` a tunnel JWT.
- `refuse_if_attack` first. Do not mock `refuse_if_attack`, `evaluate_site`.
- Reviewer never writes the code they review (D-014).
- New MUST ids phase 6, tier-less. Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. Do not waive U1.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` except Task 0.
- Copy never says “instance” except `single-instance` / `single-instance-only` in Finding/UI. Existing `instance.create` / `instance.terminate` ids stay.
- Markers: function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P6-SCALER-DEMO`. Do not mark 6.7/6.8 tests with `SCALE-OVERFLOW-JOIN-TRAFFIC`.
- TDD: failing test first. Long why HEREDOC. No amend.
- Do not edit `evaluate_all` / `CYCLE_LOCK*` / `monitor/tasks.py` / `hub/settings/base.py` / `scaling/evaluator.py` product. Do not edit `providers/cloudflare.py`. Do not fold the 6.8 leftover lock into Task 1.

Protective cut (**D-110**): MUST = Tasks 0–2.

## Parallel waves

| Shared file | Order |
|---|---|
| registry / DECISIONS / PHASE_6_MUST_IDS | Task 0 |
| `deploys/overflow.py` join + `_persist_dns_rows` + `_assemble_desired` dns_set + views / urls / ACTION_TIERS / T1_HTTP / generate-client | Task 1 after 0 |
| acceptance + demo | Task 2 after 1 |

---

### Task 0: Registry + custody (D-110…D-112)

**Files:** `DECISIONS.md`, `conformance/requirements.yaml`, `tests/test_conformance_gate.py`

- [ ] **Step 1: Failing tests** — `PHASE_6_MUST_IDS` += `SCALE-OVERFLOW-JOIN-TRAFFIC`; `allowed_sources` += `phase-6.9-design-note.md §3`. Do not rewrite `SCALE-PROPOSE-NO-PROVISION` / `SCALE-OVERFLOW-T1-ENROLL` / `SCALE-OVERFLOW-SAME-IMAGE` text. Do not re-claim `deploys/overflow.py`.
- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — copy D-110…D-112. Add the id `phase: 6`, `verify: test`, no `tier:`; `text_hash` via `--print-text-hashes`.
- [ ] **Step 4: PASS** `pytest tests/test_conformance_gate.py::test_phase_6_due_set_includes_all_section_3_must_ids tests/test_d023_actions_not_required.py tests/test_proc_rules.py -q`
- [ ] **Step 5: Commit** long why HEREDOC. No amend.

---

### Task 1: `join_overflow_traffic` + T1 HTTP + survive ensure_dns

**Files:** `deploys/overflow.py`; `deploys/steps.py` `_persist_dns_rows`; `deploys/pipeline.py` `_assemble_desired`; `core/overflow_deploys.py`; `deploys/apps.py`; `core/views.py`; `hub/urls.py`; `core/actions.py`; `tests/test_webauthn_t1.py` T1_HTTP; `frontend/src/api/action_tiers.js` via `make generate-client`; tests in `tests/test_overflow_join.py`. Do not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`. Do not edit `providers/cloudflare.py`. Do not fold the 6.8 leftover.

Reuse `_ready_site` / `_accepted_overflow` / `_ephemeral_ready` / `_plant_live_tag` / overflow deploy helpers. Plant TEST-NET-3 IPv4s on both hosts for the DNS path. Inject `FakeDnsProvider`.

- [ ] **Step 1: Failing tests** in `tests/test_overflow_join.py`

```python
@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_overflow_join_upserts_a_next_to_primary():
    # ACCEPTED, RUNNING SiteInstance, plant 203.0.113.10 / 203.0.113.20
    # FakeDns; 201 joined=dns; upsert values both IPv4s proxied=True
    # primary_target unchanged; no new Deployment; DnsRecord comma-joined
    # _assemble_desired dns_values AND dns_set keep both


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_tunnel_mode_home_joins_via_replica_not_a():
    # kind=ssh + collect_payload.tunnel True; inject replica=
    # 201 joined=tunnel; no upsert_record; replica called once


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_open_overflow_refuses_join_with_ack_is_not_launch(): ...


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_acked_overflow_refuses_join_with_ack_is_not_launch(): ...


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_evaluate_site_still_does_not_join_traffic():
    # evaluate_site does not upsert; AST bans join_overflow_traffic


def test_overflow_join_still_requires_recent_touch():
    # unmarked; T1 POST no touch → 403
```

Also pin (may live in the same file, marked when they prove the id): `site.proxied=False` upserts `proxied=False`; default replica refuse exact `tunnel replica is not configured` with no Transport; ACTION_TIERS row exact; serializer `{target, confirm_name}` only; no `\binstance\b`; 6.8 overflow deploy still no upsert.

HTTP inject: wrap real `join_overflow_traffic` with `kwargs.setdefault("dns", FakeDnsProvider())`; tunnel happy also `replica=recording`; patch `deploys.overflow.join_overflow_traffic`.

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — C1–C7, C10. generate-client. No schema. enroll/deploy unchanged.
- [ ] **Step 4: PASS** `pytest tests/test_overflow_join.py tests/test_overflow_deploy.py tests/test_overflow_enroll.py tests/test_ensure_dns.py tests/test_scale_evaluator.py tests/test_webauthn_t1.py::test_t1_action_ids_are_require_recent_touch_or_404 -q`
- [ ] **Step 5: Commit** long why HEREDOC. No amend.

---

### Task 2: Acceptance + demo append

**Files:** `tests/acceptance/test_phase_6.py`, `conformance/demos/phase-6.md`

- [ ] **Step 1:** NAMED `test_overflow_join_adds_overflow_a_next_to_primary`. Docstring transcribes §4. Body `from test_overflow_join import ...` and **calls** `test_overflow_join_upserts_a_next_to_primary` and `test_open_overflow_refuses_join_with_ack_is_not_launch`. Mark `SCALE-OVERFLOW-JOIN-TRAFFIC`. Do not mark `P6-SCALER-DEMO`. Keep 6.6/6.7/6.8 NAMED tests. Append the name to `NAMED`.
- [ ] **Step 2: RED** (demo nodeid missing / header still "No DNS join")
- [ ] **Step 3: Append** demo: FakeDns join, no live Cloudflare zone, no live AWS VM, no 30s health-pull, no auto, no AMI. Rewrite the header so it no longer says "No DNS join." Honesty: NAV six, F8 overflow seed unchanged, no Approve/Launch on the Finding.
- [ ] **Step 4: PASS** acceptance + overflow join + deploy + enroll. `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3` — new id verified; U1 uncovered-only allowed.
- [ ] **Step 5: Commit** long why HEREDOC. No amend.
