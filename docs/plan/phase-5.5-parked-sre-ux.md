# Phase 5.5 parked SRE/UX minors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land MUST-panel parked SRE F1–F3 and UX F2–F3 on T1: boot-never-up P1, poison-job Beat survival + in-batch git-push drain, rate 429 without spend-cap P1, honest `as_of`, named Suspended.

**Architecture:** No schema wave. CheckRun `INTAKE_POLL.results` gains `first_failure_at` (JSON only). `_process` becomes fail-soft per job. `_file_quota_abuse` is quota-403 only. Settings Partners reads the public `suspended` field and last-success stamp already on the list payload.

**Tech Stack:** Django, pytest, React (Settings.jsx), node:test.

**Spec:** `docs/phase-5.5-parked-sre-ux-design.md` (this wave) arguing from `docs/phase-5.5-design-note.md` r2 §7 C6/C8/C11/C12.

## Global Constraints

- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3` (D-080). No `t4`. No all-tiers 5.5. `conformance-5.5` is not a review-round prereq.
- Do not invent `HUB_TEST_CF_TOKEN` / `HUB_TEST_AWS_TOKEN` / `HUB_TEST_PARTNER_TOKEN` / `HUB_WEBHOOK_SECRET` / `HUB_INTAKE_HMAC`. Do not stub `conformance/demos/named-partner.md`. HMAC uneabled. MCP OUT.
- Do not implement Security F2 (planted SHA as `ls_remote`). Do not add a public git-webhook route. Do not ack flag-off / quota / isolation refuses. Do not reopen `0013`. No `Site.tier`.
- Function-level `@pytest.mark.req` only, on existing ids: `PART-HUB-POLL`, `PART-U2-QUOTAS`, `PART-M2-GIT-WEBHOOK`, `UX-P55-PARTNERS`. No new registry ids. Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the judging round.
- TDD: watch RED then GREEN. Tests call shipped functions (`poll`, `evaluate_quotas`, `_intake_payload` / GET `/api/v1/partners/`, `PartnersPanel`). No skip-unless on these tests.
- `intake/**` stays a separate process. `monitor/intake_poll.py` must not `import intake`. boto3 only under `providers/`. AEAD only under `vault/`.
- NAV stays six. Copy: partner site / partner-tier target, never “instance” except `single-instance`. Never paint Connected on Fake / empty `INTAKE_URL`.
- Long "why" HEREDOC commits; no amend. Work on `p55-parked-sre-ux`, never on `master`.

## File map

| File | Tasks |
|---|---|
| `monitor/intake_poll.py` | Task 1 |
| `tests/test_intake_poll.py` | Task 1 |
| `tests/test_git_webhook_outbox.py` | Task 1 (git-push drain) |
| `core/partner_verify.py` | Task 2 |
| `tests/test_partner_quotas.py` | Task 2 |
| `core/partner_views.py` | Task 3 |
| `tests/test_partner_create.py` | Task 3 |
| `frontend/src/screens/Settings.jsx` | Task 3 |
| `frontend/tests/settings-partners.test.ts` | Task 3 |

Task 1 then 2 then 3. Do not parallelize: Task 3’s `as_of` test assumes Task 1 still writes `last_success_at`.

---

### Task 1: SRE F1 boot-never-up P1 + SRE F2 poison wrap and git-push drain

**Files:**
- Modify: `monitor/intake_poll.py` (`poll`, `_process`, `_record_failure`, `_record_success`)
- Test: `tests/test_intake_poll.py`, `tests/test_git_webhook_outbox.py`

**Interfaces:**
- Consumes: existing `poll(*, client, now, sleep, jitter)`, `FakeIntakeClient`, `UNREACHABLE_AFTER`, `FAIL_N`, `TYPE_GIT_PUSH`, `_handle_git_push`, `_upsert`
- Produces: `_record_failure` may set `first_failure_at` (ISO) when `last_success_at` is missing; P1 when configured and (`last_success_at` or `first_failure_at`) is ≥ 5 min old. `_process` never raises into `poll`. Git-push items in the fetched batch run before partner-jobs.

- [ ] **Step 1: Write the failing tests** in `tests/test_intake_poll.py` (and one drain test in `tests/test_git_webhook_outbox.py`).

```python
@pytest.mark.req("PART-HUB-POLL")
def test_configured_never_up_files_p1_after_5_min():
    """Configured INTAKE_URL that never succeeds pages P1 after 5 min.

    What would make this fail: N=3 consecutive_failures filing this P1,
    requiring a prior last_success_at, moving first_failure_at, or paging
    empty INTAKE_URL after five minutes.
    """
    from core.models import CheckRun, Finding
    from monitor.intake_poll import FakeIntakeClient, poll

    t0 = timezone.now()
    with override_settings(INTAKE_URL=""):
        for now in (t0, t0 + timedelta(minutes=5)):
            result = poll(now=now, jitter=0, sleep=lambda _s: None)
            assert result["status"] == CheckRun.Status.SKIPPED
        assert CheckRun.objects.filter(kind=CheckRun.Kind.INTAKE_POLL).count() == 0
        assert not Finding.objects.filter(
            fingerprint="partner-intake-unreachable",
        ).exists()
        assert not Finding.objects.filter(
            fingerprint="hub-outbox-poll-failing",
        ).exists()

    client = FakeIntakeClient(fail=True)
    with override_settings(INTAKE_URL="http://intake.test"):
        for _ in range(3):
            poll(client=client, now=t0, jitter=0, sleep=lambda _s: None)
        assert Finding.objects.filter(
            fingerprint="hub-outbox-poll-failing",
        ).exists()
        assert not Finding.objects.filter(
            fingerprint="partner-intake-unreachable",
        ).exists()
        latest = CheckRun.objects.get(kind=CheckRun.Kind.INTAKE_POLL)
        first = (latest.results or {}).get("first_failure_at")
        assert first
        poll(
            client=client, now=t0 + timedelta(minutes=4),
            jitter=0, sleep=lambda _s: None,
        )
        latest = CheckRun.objects.get(kind=CheckRun.Kind.INTAKE_POLL)
        assert (latest.results or {}).get("first_failure_at") == first
        assert not Finding.objects.filter(
            fingerprint="partner-intake-unreachable",
        ).exists()
        poll(
            client=client, now=t0 + timedelta(minutes=5),
            jitter=0, sleep=lambda _s: None,
        )
    row = Finding.objects.get(fingerprint="partner-intake-unreachable")
    assert row.severity == "p1"
    assert not Finding.objects.filter(
        fingerprint="partner-intake-unreachable:intake",
    ).exists()


@pytest.mark.req("PART-HUB-POLL")
def test_poison_outbox_item_does_not_kill_beat_or_arm_c12():
    """A non-dict outbox row must not raise out of poll or increment fetch failures.

    What would make this fail: job.get on a str, wrapping fetch so Beat
    lives but C12 never arms, or counting the poison as consecutive_failures.
    """
    from core.models import CheckRun, Finding
    from monitor.intake_poll import FakeIntakeClient, poll

    client = FakeIntakeClient(items=["poison", {"id": "later", "type": "partner-job"}])
    now = timezone.now()
    with override_settings(INTAKE_URL="http://intake.test", PARTNER_API_ENABLED=False):
        result = poll(client=client, now=now, jitter=0, sleep=lambda _s: None)
        assert result["ok"] is True
        assert result["status"] == "succeeded"
        latest = CheckRun.objects.get(kind=CheckRun.Kind.INTAKE_POLL)
        assert int((latest.results or {}).get("consecutive_failures") or 0) == 0
        assert not Finding.objects.filter(
            fingerprint="hub-outbox-poll-failing",
        ).exists()
        client.fail = True
        for _ in range(3):
            poll(client=client, now=now, jitter=0, sleep=lambda _s: None)
    p2 = Finding.objects.get(fingerprint="hub-outbox-poll-failing")
    assert p2.severity == "p2"
    assert not Finding.objects.filter(
        fingerprint="hub-outbox-poll-failing:intake",
    ).exists()
```

In `tests/test_git_webhook_outbox.py`, add (reuse `_git_site`, `_patch_delay`, `_boom_ls_remote`, `GIT_URL`, `NEW_SHA` already in that file):

```python
@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_git_push_in_same_batch_runs_before_skip_ack_partner_jobs(monkeypatch):
    """A git-push behind skip-ack partner-jobs in the fetched batch still enqueues.

    What would make this fail: processing strictly in list order and returning
    before the git-push, or a second fetch.
    """
    from monitor.intake_poll import FakeIntakeClient, poll

    queued = _patch_delay(monkeypatch)
    site = _git_site(slug="git-drain")
    client = FakeIntakeClient()
    for i in range(3):
        client.items.append({
            "id": f"job-skip-{i}", "type": "partner-job", "action": "site.create",
        })
    client.plant_git_push(GIT_URL, "main", NEW_SHA, job_id="job-git-drain")
    _boom_ls_remote(monkeypatch)
    with override_settings(PARTNER_API_ENABLED=False):
        result = poll(client=client, jitter=0, sleep=lambda _s: None)
    assert result["ok"] is True
    assert client.fetch_calls == 1
    assert "job-git-drain" in client.acked
    assert queued == [
        Deployment.objects.exclude(status=Deployment.Status.SUCCEEDED)
        .get(manifest__site=site).pk
    ]
    for i in range(3):
        assert f"job-skip-{i}" not in client.acked
```

Keep `test_empty_intake_url_skips_and_does_not_file_p1` and
`test_unreachable_over_5_min_files_partner_intake_unreachable` green.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_intake_poll.py::test_configured_never_up_files_p1_after_5_min tests/test_intake_poll.py::test_poison_outbox_item_does_not_kill_beat_or_arm_c12 tests/test_git_webhook_outbox.py::test_git_push_in_same_batch_runs_before_skip_ack_partner_jobs -q`

Expected: never-up FAIL (no `first_failure_at` / no P1 at +5 min, or P1 already at N=3 if someone keys P1 off consecutive_failures — the t0×3 tick must not file P1). Poison is pytest ERROR on HEAD (`str` has no `.get`) then, after wrap-only, would miss the trailing N=3 P2 pin. Drain test is a pin: **PASS on HEAD** (`if not enabled: continue` already walks the list). Keep git-first anyway so a later `return` cannot skip the tail. Do not invent a RED that requires an early `return`.

- [ ] **Step 3: Minimal implementation**

In `_record_failure`:

- Read `last_success_at` and `first_failure_at` from prev results.
- If `last_success_at` is missing/unparsable and `first_failure_at` is missing, set `first_failure_at` to `_iso(now)`.
- Persist both on the upsert.
- File P1 when `now - last_success_at >= UNREACHABLE_AFTER` **or** (no parsable `last_success_at` and `now - first_failure_at >= UNREACHABLE_AFTER`).
- Empty URL never reaches this function.

In `_record_success`: set `consecutive_failures=0`, `last_success_at=_iso(now)`, and omit / clear `first_failure_at`. `first_failure_at` must not move once set.

Harden `FakeIntakeClient.ack` so remaining non-dicts are skipped (`isinstance(item, dict) and item.get("id") == job_id`), not `item.get` on a str.

In `_process`:

```python
def _iter_jobs_git_first(items):
    git_push, other = [], []
    for job in items:
        if isinstance(job, dict) and (job.get("type") or "") == TYPE_GIT_PUSH:
            git_push.append(job)
        else:
            other.append(job)
    return git_push + other


def _process(client, items, now):
    from core.audit import audit
    from core.partner_jobs import PartnerNotFound, PartnerRefuse, materialize
    from core.partner_verify import ReplayRejected, SignatureRejected

    n = 0
    enabled = bool(getattr(settings, "PARTNER_API_ENABLED", False))
    for job in _iter_jobs_git_first(items):
        try:
            if not isinstance(job, dict):
                audit("outbox-item-refused", source="celery", severity="warning",
                      type=type(job).__name__)
                continue
            job_id = job.get("id")
            job_type = job.get("type") or TYPE_PARTNER_JOB
            if job_type == TYPE_GIT_PUSH:
                n += int(bool(_handle_git_push(job, now)))
                _ack(client, job_id)
                continue
            if job_type != TYPE_PARTNER_JOB:
                _refuse_unknown(job)
                _ack(client, job_id)
                continue
            if not enabled:
                continue
            partner, result = _partner_for(job, now)
            if partner is None or result is None or not result.ok:
                continue
            n += 1
            created = materialize(partner, job)
            if created is None:
                continue
            if _ack(client, job_id):
                _persist_accepted_nonce(partner, result, now)
                _persist_accepted_idempotency(partner, job, result)
        except ReplayRejected:
            if isinstance(job, dict):
                _ack(client, job.get("id"))
            continue
        except (SignatureRejected, PartnerRefuse, PartnerNotFound):
            continue
        except Exception:
            from core.audit import audit as _audit
            _audit("outbox-item-refused", source="celery", severity="warning")
            continue
    return n
```

Do **not** collapse ReplayRejected into the bare `except Exception` (replay must still ack). Do not `_record_failure` from `_process`. Import `audit` once at the top of `_process` rather than inside the except if the file already imports it for `_refuse_unknown`.

Do not change `enqueue_git_push` / `ls_remote`. Do not `import intake`.

- [ ] **Step 4: Run the new tests plus neighbors**

Run: `pytest tests/test_intake_poll.py tests/test_git_webhook_outbox.py tests/test_partner_isolation.py -q`

Expected: PASS. Empty URL still zero CheckRuns / zero P1.

- [ ] **Step 5: Commit**

```bash
git add monitor/intake_poll.py tests/test_intake_poll.py tests/test_git_webhook_outbox.py
git commit -m "$(cat <<'EOF'
A configured intake that never comes up never paged, and a poison outbox row killed Beat.

first_failure_at starts the C6 5-minute clock when last_success_at is missing.
Per-job wrap plus git-first drain keep the 10 s poller recording success
instead of raising, without acking flag-off jobs or treating planted SHA
as ls_remote.
EOF
)"
```

---

### Task 2: SRE F3 rate 429 does not file spend-cap P1

**Files:**
- Modify: `core/partner_verify.py` (`_refuse` / `_file_quota_abuse` call)
- Test: `tests/test_partner_quotas.py`

**Interfaces:**
- Consumes: `evaluate_quotas`, `_plant_nonces`, `_plant_deploys`, `_partner`, existing `test_quota_abuse_files_budget_cap_hit_partner`, `test_rate_limit_60_and_deploy_create_3_per_min`
- Produces: quota 403 still files `budget-cap-hit:partner`; rate 429 does not.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.req("PART-U2-QUOTAS")
def test_rate_429_does_not_file_budget_cap_hit_partner():
    """Rate floors refuse 429 without the quota-abuse spend-cap P1.

    What would make this fail: _refuse("rate") calling _file_quota_abuse, or
    dropping the 429 / X-RateLimit-* refuse itself.
    """
    from datetime import timedelta

    from core.models import Finding
    from core.partner_verify import evaluate_quotas

    now = timezone.now()
    general_partner = _partner("q-rl-no-p1")
    _plant_nonces(general_partner, 60, now=now)
    general = evaluate_quotas(
        general_partner, "GET", "/partner/v1/deployments/1", now=now,
    )
    assert general.refused is True
    assert general.reason == "rate"
    assert general.status == 429
    _assert_rate_headers(general.headers, limit=60)
    assert not Finding.objects.filter(fingerprint="budget-cap-hit:partner").exists()

    burst_partner = _partner("q-rl-burst-no-p1", deploys_per_day=500, max_sites=10)
    burst_site = _bind_sites(burst_partner, 1)[0]
    deploy_path = f"/partner/v1/sites/{burst_site.pk}/deployments"
    _plant_deploys(burst_site, 3, created_at=now - timedelta(seconds=10))
    burst = evaluate_quotas(burst_partner, "POST", deploy_path, now=now)
    assert burst.refused is True
    assert burst.reason == "rate"
    assert burst.status == 429
    assert not Finding.objects.filter(fingerprint="budget-cap-hit:partner").exists()
```

Do not change D-084 text. `test_quota_abuse_files_budget_cap_hit_partner` must stay green.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_partner_quotas.py::test_rate_429_does_not_file_budget_cap_hit_partner -q`

Expected: FAIL (`budget-cap-hit:partner` exists).

- [ ] **Step 3: Minimal implementation**

In `evaluate_quotas`’s `_refuse`:

```python
def _refuse(reason, status, headers):
    if reason != "rate":
        _file_quota_abuse(partner, reason)
    return QuotaDecision(
        True, reason=reason, status=status, headers=headers,
    )
```

No new alert kind. No fingerprint other than the existing quota one.

- [ ] **Step 4: Run**

Run: `pytest tests/test_partner_quotas.py -q`

Expected: PASS, including `test_quota_abuse_files_budget_cap_hit_partner`.

- [ ] **Step 5: Commit**

```bash
git add core/partner_verify.py tests/test_partner_quotas.py
git commit -m "$(cat <<'EOF'
A 4th deploy in a minute filed the same P1 as a hard max_sites refuse.

Rate 429 still refuses with X-RateLimit-* headers. Only quota 403 upserts
budget-cap-hit:partner, so a rate floor no longer looks like the AWS spend cap.
EOF
)"
```

---

### Task 3: UX F2 last-confirmed as_of + UX F3 named Suspended

**Files:**
- Modify: `core/partner_views.py` (`_intake_payload`)
- Modify: `frontend/src/screens/Settings.jsx` (PartnersPanel row)
- Test: `tests/test_partner_create.py`, `frontend/tests/settings-partners.test.ts`

**Interfaces:**
- Consumes: `CheckRun.Kind.INTAKE_POLL` results `last_success_at`; `PartnerPublic.suspended`; existing `intakeLine` stamp formatting
- Produces: GET `/api/v1/partners/` `intake.as_of` is the last successful poll ISO or null; PartnersPanel visible text includes `Suspended` when `p.suspended`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_partner_create.py`:

```python
@pytest.mark.req("UX-P55-PARTNERS")
def test_intake_as_of_is_last_success_not_now(client):
    """as_of is last_success_at from INTAKE_POLL, never timezone.now().

    What would make this fail: stamping now() on the error path, using
    first_failure_at, or omitting as_of when last_success_at exists.
    """
    from datetime import timedelta

    from core.models import CheckRun
    from django.utils import timezone
    from monitor.alerts import raise_alert

    _t1_user(client)
    raise_alert(
        "partner-intake-unreachable",
        "intake",
        fingerprint="partner-intake-unreachable",
        source_engine="monitor.intake_poll",
        title="Partner intake unreachable",
        body="fixture",
        fix_action="fixture",
    )
    stamp = (timezone.now() - timedelta(minutes=6)).isoformat()
    CheckRun.objects.create(
        kind=CheckRun.Kind.INTAKE_POLL,
        status=CheckRun.Status.FAILED,
        results={"schema_version": 1, "last_success_at": stamp,
                 "consecutive_failures": 3},
        started=timezone.now(),
        finished=timezone.now(),
    )
    before = timezone.now()
    response = client.get(CREATE_URL)
    after = timezone.now()
    assert response.status_code == 200
    intake = response.json()["intake"]
    assert intake["status"] == "error"
    assert intake["as_of"] == stamp
    assert intake["as_of"] != before.isoformat()
    assert intake["as_of"] != after.isoformat()


@pytest.mark.req("UX-P55-PARTNERS")
def test_intake_as_of_is_null_when_never_succeeded(client):
    """Never-success as_of is null even when intake status is error.

    What would make this fail: falling back to timezone.now() or
    first_failure_at when last_success_at is missing.
    """
    from core.models import CheckRun
    from django.utils import timezone
    from monitor.alerts import raise_alert

    _t1_user(client)
    raise_alert(
        "partner-intake-unreachable",
        "intake",
        fingerprint="partner-intake-unreachable",
        source_engine="monitor.intake_poll",
        title="Partner intake unreachable",
        body="fixture",
        fix_action="fixture",
    )
    CheckRun.objects.create(
        kind=CheckRun.Kind.INTAKE_POLL,
        status=CheckRun.Status.FAILED,
        results={"schema_version": 1, "first_failure_at": timezone.now().isoformat(),
                 "consecutive_failures": 3},
        started=timezone.now(),
        finished=timezone.now(),
    )
    before = timezone.now()
    response = client.get(CREATE_URL)
    after = timezone.now()
    assert response.status_code == 200
    intake = response.json()["intake"]
    assert intake["status"] == "error"
    assert intake["as_of"] is None
    assert intake["as_of"] != before.isoformat()
    assert intake["as_of"] != after.isoformat()
```

In `frontend/tests/settings-partners.test.ts`:

```typescript
test("suspended_partner_row_names_suspended_in_words", () => {
  const live = visibleText(render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
      suspended: false }],
    intake: { status: "degraded", mode: "fake", configured: false },
  }));
  assert.match(live, /fixture-partner/);
  assert.doesNotMatch(live, /Suspended/);

  const stopped = visibleText(render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
      suspended: true }],
    intake: { status: "degraded", mode: "fake", configured: false },
  }));
  assert.match(stopped, /fixture-partner/);
  assert.match(stopped, /Suspended/);
  assert.doesNotMatch(stopped, /\bConnected\b/);
  assert.doesNotMatch(stopped, /\binstance\b/i);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_partner_create.py::test_intake_as_of_is_last_success_not_now tests/test_partner_create.py::test_intake_as_of_is_null_when_never_succeeded -q`

Expected: first test FAIL because HEAD stamps `timezone.now()` on the error path (or ignores CheckRun). Second test FAIL if `as_of` is now() / `first_failure_at` instead of null.

Run: `node --import tsx --test frontend/tests/settings-partners.test.ts`

Expected: FAIL on `/Suspended/` (or the new test not found until added — then assertion fail).

- [ ] **Step 3: Minimal implementation**

`core/partner_views.py` `_intake_payload`:

```python
def _intake_payload():
    from core.models import CheckRun, Finding

    url = str(getattr(settings, "INTAKE_URL", "") or "").strip()
    error = Finding.objects.filter(
        fingerprint="partner-intake-unreachable",
    ).exclude(state=Finding.State.RESOLVED).exists()
    latest = (
        CheckRun.objects.filter(kind=CheckRun.Kind.INTAKE_POLL)
        .order_by("-pk")
        .first()
    )
    last_success = None
    if latest is not None:
        last_success = ((latest.results or {}).get("last_success_at") or None)
    return {
        "status": "error" if error else "degraded",
        "mode": "fake" if not url else "configured",
        "configured": bool(url),
        "as_of": last_success,
    }
```

Do not call `timezone.now()` for `as_of`. Do not copy `first_failure_at` into `as_of`. Finding import stays if already used; `CheckRun` is in `core.models`.

`PartnersPanel` row: after `<strong>{p.slug}</strong>`, if `p.suspended` render a sibling with the word `Suspended` (text, not color-only). Keep suspend ActionButton. Do not add a picker. Do not say Connect / Connected / instance.

- [ ] **Step 4: Run**

Run: `pytest tests/test_partner_create.py -q` and `node --import tsx --test frontend/tests/settings-partners.test.ts`

Expected: PASS. Existing never-Connected / Create partner tests stay green.

- [ ] **Step 5: Commit**

```bash
git add core/partner_views.py tests/test_partner_create.py frontend/src/screens/Settings.jsx frontend/tests/settings-partners.test.ts
git commit -m "$(cat <<'EOF'
Intake error stamped now() as last-confirmed, and a suspended partner still looked live.

as_of is the INTAKE_POLL last_success_at (or null). The Partners row names
Suspended in words after T1 suspend so the flag is not chrome-invisible.
EOF
)"
```
