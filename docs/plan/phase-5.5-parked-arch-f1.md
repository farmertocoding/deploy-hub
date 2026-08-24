# Phase 5.5 parked Architect F1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `core` does not import `deploys`. Partner materialize and U2 deploy-count still happen.

**Architecture:** `PartnerDeployStore` lives in `core/partner_deploys.py`. `deploys/partner_ledger.py` implements it. `deploys.apps.DeploysConfig.ready()` calls `register_store` (same arrow as `core.events` / `realtime.apps.ready()`). `core/partner_jobs.py` stays the r2 materialize home and must not `import deploys`.

**Tech Stack:** Django, pytest. T1 uses the wired Django ORM store (no Fake ledger).

**Spec:** `docs/phase-5.5-parked-arch-f1-design.md` arguing from `docs/phase-5.5-design-note.md` r2 D4/D5 and `core/models.py` L5.

## Global Constraints

- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3` (D-080). No `t4`. No all-tiers 5.5. `conformance-5.5` is not a review-round prereq.
- Do not invent `HUB_TEST_*` tokens. Do not stub `named-partner.md`. HMAC uneabled. MCP OUT. No `Site.tier` / `Site.partner_id` / `Target.tier`.
- Do not reopen U1, Phase 6, UX F1 picker, Security F2 git-push, parked F3–F5.
- Do not reopen `0013`. Do not add `0014`. Do not edit `core/models.py`.
- Function-level `@pytest.mark.req("ARCH-D4-IMPORT-RULE")` on new import-rule tests. No new registry ids. Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml`. Do not claim `deploys/**` or `core/partner_deploys.py` on `paths.yaml` (peer of `core/events.py`).
- Do not move `core/partner_jobs.py` into `deploys/`. Do not add PartnerSite counters. Do not add a fallback `from deploys.models import …` inside core. `monitor/intake_poll.py` still calls `core.partner_jobs.materialize`. Isolation is still Partner + PartnerSite + `destination_order`. Intake wall unchanged (`import intake` still forbidden from Hub product).
- Do not register the store from `tests/conftest.py`. Do not skip `DeploysConfig.ready()` when `DEBUG`. INSTALLED_APPS stays `"deploys"` (not a dotted `DeploysConfig` path). Do not add a Beat / CheckRun / extra poller to wire the store. Do not change `_reaches` itself. Do not delete `monitor → deploys` (M2 / retention). Kernel tooth is `"deploys" not in _direct_imports("core")`, **not** `_reaches("core", "deploys") is None`.
- The wired store is Django ORM. Tests keep planting `Manifest` / `Deployment` via `deploys.models`. Do not ship an in-memory Fake that would hide IDOR / quota misses.
- TDD: watch RED then GREEN. Long "why" HEREDOC commits; no amend. Work on `p55-arch-f1`, never on `master`. Never push. Never merge.

## File map

| File | Tasks |
|---|---|
| `tests/test_import_rule.py` | Task 1, Task 2 |
| `tests/test_partner_quotas.py` | Task 2 (`test_unwired_evaluate_quotas_deploy_create_fails_loud`) |
| `core/partner_deploys.py` | Task 1 (new); Task 2 adds `count_since` |
| `deploys/partner_ledger.py` | Task 1 (new); Task 2 adds `count_since` |
| `deploys/apps.py` | Task 1 |
| `core/partner_jobs.py` | Task 1 |
| `core/partner_verify.py` | Task 2 |

Task 1 then Task 2. Do not merge Task 1 alone — the kernel gate is Task 2.

---

### Task 1: Port + ledger — partner_jobs does not import deploys

**Files:**
- Create: `core/partner_deploys.py`, `deploys/partner_ledger.py`
- Modify: `deploys/apps.py`, `core/partner_jobs.py`
- Test: `tests/test_import_rule.py`

**Interfaces:**
- Consumes: `Partner`, `PartnerSite`, `Site`; existing `MaterializeResult`
- Produces: `PartnerDeployStore.get_deployment` / `find_by_job_id` / `create_queued`; `register_store` from `DeploysConfig.ready()`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_import_rule.py` (module already imports `re`, `pytest`, `REPO`):

```python
@pytest.mark.req("ARCH-D4-IMPORT-RULE")
def test_partner_jobs_does_not_import_deploys():
    """r2 materialize home must not import deploys, even lazily.

    What would make this fail: get_partner_deployment / _existing_deployment /
    _create doing `from deploys.models import Deployment` at function level
    so Django still loads while the kernel docstring is a lie.
    """
    src = (REPO / "core" / "partner_jobs.py").read_text(encoding="utf-8")
    assert re.search(r"^\s*(?:from|import)\s+deploys\b", src, re.M) is None, (
        "core/partner_jobs.py imports deploys"
    )


@pytest.mark.req("ARCH-D4-IMPORT-RULE")
def test_ready_wires_partner_deploy_store(monkeypatch):
    """DeploysConfig.ready() registers the ORM ledger. Unwired fails loud.

    What would make this fail: register_store only from tests/conftest.py,
    a ready() that stops registering or skips when DEBUG, or store()
    returning a zeroing stand-in when _store is None.
    """
    from django.apps import apps as django_apps
    import core.partner_deploys as port
    from deploys.partner_ledger import DjangoPartnerDeployStore

    monkeypatch.setattr(port, "_store", None)
    with pytest.raises(RuntimeError, match="not wired"):
        port.store()
    django_apps.get_app_config("deploys").ready()
    assert isinstance(port.store(), DjangoPartnerDeployStore)
```

- [ ] **Step 2: Run to verify RED**

`/Users/j/j/deploy-hub/.venv/bin/pytest tests/test_import_rule.py::test_partner_jobs_does_not_import_deploys tests/test_import_rule.py::test_ready_wires_partner_deploy_store -q`

Expected: FAIL (`core/partner_jobs.py imports deploys`) and ImportError / no `DeploysConfig.ready` until the port exists. `_direct_imports` already sees the three indented `from deploys.models import …` lines; this test names the r2 home before Task 2's package walk.

- [ ] **Step 3: Minimal implementation**

`core/partner_deploys.py` (Transport-style class, not `typing.Protocol`):

```python
"""D4 port: Manifest/Deployment live in deploys. Core never imports them.

Wired once from deploys.apps.DeploysConfig.ready(), the same arrow as
core.events / realtime.apps.ready(). Unwired calls fail loud.
"""

_store = None


class PartnerDeployStore:
    def get_deployment(self, partner, deployment_id):
        raise NotImplementedError

    def find_by_job_id(self, partner, job_id):
        raise NotImplementedError

    def create_queued(self, site, body):
        raise NotImplementedError


def register_store(store):
    global _store
    _store = store


def _require():
    if _store is None:
        raise RuntimeError(
            "partner deploy store not wired — deploys.apps.DeploysConfig.ready() "
            "must call core.partner_deploys.register_store()"
        )
    return _store


def store():
    return _require()
```

`deploys/partner_ledger.py` — copy today's querysets, do not invent filters:

```python
"""Django ORM adapter for core.partner_deploys.PartnerDeployStore."""
from core.partner_deploys import PartnerDeployStore
from deploys.models import Deployment, Manifest


class DjangoPartnerDeployStore(PartnerDeployStore):
    def get_deployment(self, partner, deployment_id):
        return Deployment.objects.filter(
            pk=deployment_id,
            manifest__site__partner_site__partner=partner,
        ).first()

    def find_by_job_id(self, partner, job_id):
        if not job_id:
            return None
        qs = Deployment.objects.filter(
            manifest__site__partner_site__partner=partner,
        ).select_related("manifest", "manifest__site")
        for dep in qs:
            if (dep.manifest.body or {}).get("partner_job_id") == job_id:
                return dep
        return None

    def create_queued(self, site, body):
        last = site.manifests.order_by("-version").values_list(
            "version", flat=True,
        ).first()
        version = (last or 0) + 1
        manifest = Manifest.objects.create(
            site=site, version=version, body=body,
        )
        deployment = Deployment.objects.create(
            manifest=manifest, status=Deployment.Status.QUEUED,
        )
        return manifest, deployment
```

`deploys/apps.py` — add `ready()` (keep existing `DeploysConfig`; INSTALLED_APPS stays `"deploys"`):

```python
def ready(self):
    # Core must not import deploys (kernel docstring / D4). The adapter
    # is plugged in here, the direction imports are already allowed to
    # point — same as realtime.apps.ready → core.events.register_stream.
    from core.partner_deploys import register_store
    from deploys.partner_ledger import DjangoPartnerDeployStore

    register_store(DjangoPartnerDeployStore())
```

`core/partner_jobs.py` — drop every `from deploys.models import …`. Keep PartnerSite/Project/Site mint and template body in this file:

```python
def get_partner_deployment(partner, deployment_id):
    from core.partner_deploys import store

    dep = store().get_deployment(partner, deployment_id)
    if dep is None:
        raise PartnerNotFound()
    return dep


def _existing_deployment(partner, job_id):
    from core.partner_deploys import store

    if not job_id:
        return None
    dep = store().find_by_job_id(partner, job_id)
    if dep is None:
        return None
    site = dep.manifest.site
    return MaterializeResult(site, site.partner_site, dep.manifest, dep)
```

In `_create`, after `site` / `binding` exist, replace Manifest/Deployment construction + `site.manifests` version bump with:

```python
    from core.partner_deploys import store

    manifest, deployment = store().create_queued(
        site,
        {
            "schema_version": 1,
            "runtime": "static",
            "image_digest": digest,
            "template_ref": TEMPLATE_REF,
            "partner_job_id": job.get("id"),
            "ship_mode": "load",
        },
    )
    return MaterializeResult(site, binding, manifest, deployment)
```

Do not move `_create`'s Project / Site / PartnerSite / `_require_quota` block. Do not change `materialize()` signature. Do not edit `monitor/intake_poll.py`. Do not implement `count_since` yet.

- [ ] **Step 4:** `/Users/j/j/deploy-hub/.venv/bin/pytest tests/test_import_rule.py::test_partner_jobs_does_not_import_deploys tests/test_import_rule.py::test_ready_wires_partner_deploy_store tests/test_partner_isolation.py::test_partner_a_404s_on_partner_b_ids tests/test_partner_isolation.py::test_digest_pinned_fixture_template_deploys tests/test_partner_isolation.py::test_materialize_run_twice_zero_mutating_calls tests/test_partner_isolation.py::test_flag_off_does_not_create_deployment -q` PASS.

`get_partner_deployment` still 404s on the other partner's Deployment. Digest-pinned fixture still QUEUED. Same `partner_job_id` still one Deployment (D6). Flag-off still creates nothing.

- [ ] **Step 5: Commit**

```bash
git add tests/test_import_rule.py core/partner_deploys.py deploys/partner_ledger.py deploys/apps.py core/partner_jobs.py
git commit -m "$(cat <<'EOF'
Function-level deploys.models imports let partner_jobs write Manifest rows
while the kernel docstring forbade core from importing deploys.

Lookups and queued inserts now go through a core port wired from
deploys.apps.ready, the same arrow as events/realtime, so the r2
materialize home stays in core without the load-time cycle.
EOF
)"
```

---

### Task 2: Quota counts + kernel `"deploys" not in _direct_imports("core")` gate

**Files:**
- Modify: `core/partner_deploys.py`, `deploys/partner_ledger.py`, `core/partner_verify.py`
- Test: `tests/test_import_rule.py`, `tests/test_partner_quotas.py`

**Interfaces:**
- Consumes: Task 1 store; `evaluate_quotas` deploy-create branch
- Produces: `count_since(partner, since, site=None)`; `test_core_stays_free_of_deploys`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_import_rule.py`:

```python
@pytest.mark.req("ARCH-D4-IMPORT-RULE")
def test_core_stays_free_of_deploys():
    """core is the shared kernel: a deploys dependency here becomes a deploys
    dependency in every app (core/models.py L5). Function-level imports count.

    What would make this fail: core/partner_verify.py (or any core module)
    `from deploys.models import Deployment`, or moving that import into a
    helper still under core/.
    """
    assert "deploys" not in _direct_imports("core"), (
        "core imports deploys (function-level counts)"
    )


@pytest.mark.req("ARCH-D4-IMPORT-RULE")
def test_core_deploys_detector_actually_detects():
    """The test above passes trivially if _direct_imports cannot see deploys."""
    assert "deploys" in _direct_imports("wizard")
    assert _reaches("wizard", "deploys") is not None
    # Legal M2 path: do not assert _reaches("core", "deploys") is None.


```

Also append to `tests/test_partner_quotas.py` (uses `_partner`; django_db already):

```python
@pytest.mark.req("ARCH-D4-IMPORT-RULE")
def test_unwired_evaluate_quotas_deploy_create_fails_loud(monkeypatch):
    """Unwired store must not fail-open as count 0 on partner deploy-create.

    What would make this fail: except Exception: day_count = 0, or a
    zeroing stand-in when _store is None.
    """
    import core.partner_deploys as port
    from core.partner_verify import evaluate_quotas
    from django.apps import apps as django_apps

    partner = _partner("q-unwired")
    monkeypatch.setattr(port, "_store", None)
    with pytest.raises(RuntimeError, match="not wired"):
        evaluate_quotas(partner, "POST", "/partner/v1/sites/x/deployments")
    django_apps.get_app_config("deploys").ready()
```

- [ ] **Step 2: Run to verify RED**

`/Users/j/j/deploy-hub/.venv/bin/pytest tests/test_import_rule.py::test_core_stays_free_of_deploys tests/test_import_rule.py::test_core_deploys_detector_actually_detects tests/test_partner_quotas.py::test_unwired_evaluate_quotas_deploy_create_fails_loud -q`

Expected: `test_core_stays_free_of_deploys` FAIL (`core imports deploys`) from `core/partner_verify.py`'s function-level `from deploys.models import Deployment`. Detector PASS (`wizard` is allowed to import deploys). Unwired quotas FAIL until `evaluate_quotas` calls `store()` (or FAIL because `_store` is still None and the old Deployment import path does not raise `not wired`). After Task 1, partner_jobs is not in `_direct_imports("core")` except via partner_verify.

- [ ] **Step 3: Minimal implementation**

Add on `PartnerDeployStore` and `DjangoPartnerDeployStore`:

```python
def count_since(self, partner, since, site=None):
    raise NotImplementedError
```

```python
def count_since(self, partner, since, site=None):
    qs = Deployment.objects.filter(manifest__created_at__gte=since)
    if site is not None:
        qs = qs.filter(manifest__site=site)
    else:
        qs = qs.filter(manifest__site__partner_site__partner=partner)
    return qs.count()
```

Per-site must **not** also filter `partner` (today's shape; the site is already PartnerSite-resolved). Timestamp column stays `manifest__created_at` (Deployment has no `created_at`).

`core/partner_verify.py` `evaluate_quotas`: drop `from deploys.models import Deployment`. In the POST deploy-create branch:

```python
    from core.partner_deploys import store

    ledger = store()
    day_count = ledger.count_since(partner, day_start)
    if day_count >= deploys_per_day:
        return _refuse("quota", 403, general_headers)
    site = _resolve_partner_site(partner, deploy_match.group(1))
    if site is not None:
        per_min = ledger.count_since(partner, minute_start, site=site)
        deploy_headers = _rate_headers(
            RATE_DEPLOY_CREATE_PER_MIN, per_min, reset_unix,
        )
        if per_min >= RATE_DEPLOY_CREATE_PER_MIN:
            return _refuse("rate", 429, deploy_headers)
        per_day = ledger.count_since(partner, day_start, site=site)
        if per_day >= RATE_DEPLOY_CREATE_PER_DAY:
            return _refuse("rate", 429, _rate_headers(
                RATE_DEPLOY_CREATE_PER_DAY, per_day, reset_unix,
            ))
        return QuotaDecision(False, headers=deploy_headers)
```

Do not change max_sites / fleet / domains / nonce rate (those stay on Partner / PartnerSite / PartnerReplayNonce). Do not add PartnerSite counter columns. Do not file `budget-cap-hit:partner` on `reason=="rate"`. No fallback `import deploys`.

- [ ] **Step 4:** `/Users/j/j/deploy-hub/.venv/bin/pytest tests/test_import_rule.py tests/test_partner_quotas.py::test_unwired_evaluate_quotas_deploy_create_fails_loud tests/test_partner_quotas.py::test_deploys_per_day_default_50 tests/test_partner_quotas.py::test_rate_limit_60_and_deploy_create_3_per_min tests/test_partner_quotas.py::test_rate_429_does_not_file_budget_cap_hit_partner tests/test_partner_isolation.py::test_digest_pinned_fixture_template_deploys tests/test_partner_isolation.py::test_partner_a_404s_on_partner_b_ids -q` PASS.

51st partner deploy-create still 403 `quota`. 4th per-site minute still 429 `rate` without `budget-cap-hit:partner`. `"deploys" not in _direct_imports("core")`. `test_cloud_sdk_imports_only_under_providers` and `test_core_stays_free_of_scanner` still PASS. Do not assert `_reaches("core", "deploys") is None`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_import_rule.py tests/test_partner_quotas.py core/partner_deploys.py deploys/partner_ledger.py core/partner_verify.py
git commit -m "$(cat <<'EOF'
evaluate_quotas counted U2 deploys by importing Deployment, so the new
core ↛ deploys walk stayed red after partner_jobs dropped its edge.

Quota counts now go through the same wired store, and the import-rule
tooth fails closed on any core helper that grows the cycle back.
EOF
)"
```
