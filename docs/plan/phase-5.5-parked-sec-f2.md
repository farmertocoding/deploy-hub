# Phase 5.5 parked Security F2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A compromised intake cannot force an operator git-sourced site to a historical SHA; git-push is a wake-up, git host is the head.

**Architecture:** `enqueue_git_push` still validates the planted URL, then wraps `poll()` with a lookup that calls `git_ls_remote` only for matching `Project.git_url` + `git_ref`. The wrapper never returns the planted `sha`.

**Tech Stack:** Django, pytest. T1 injects `deploys.poller.git_ls_remote`.

**Spec:** `docs/phase-5.5-parked-sec-f2-design.md` arguing from `docs/phase-5.5-design-note.md` r2 §7 C6 / D-085.

## Global Constraints

- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3` (D-080). No `t4`. No all-tiers 5.5.
- Do not invent `HUB_TEST_*` tokens. Do not stub `named-partner.md`. HMAC uneabled. MCP OUT. No public git-webhook route. No intake secret.
- Function-level `@pytest.mark.req("PART-M2-GIT-WEBHOOK")` on new tests. No new registry ids. Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml`.
- `monitor/intake_poll.py` must not `import intake`. T1 tests never hit the network (`git_ls_remote` injected).
- Git-push still runs when `PARTNER_API_ENABLED` is False. Do not ack flag-off partner-jobs.
- TDD: watch RED then GREEN. Long "why" HEREDOC commits; no amend. Work on `p55-sec-f2`, never on `master`.

## File map

| File | Role |
|---|---|
| `deploys/poller.py` | `enqueue_git_push` wake-up wrapper |
| `tests/test_git_webhook_outbox.py` | F2 pins + rewrite `_boom_ls_remote` callers that enqueue |

---

### Task 1: Wake-up enqueue — planted SHA is not the head

**Files:**
- Modify: `deploys/poller.py` (`enqueue_git_push`)
- Modify: `tests/test_git_webhook_outbox.py`

**Interfaces:**
- Consumes: `validate_git_url`, `poll()`, `git_ls_remote`, Fake-plant `{type, git_url, ref, sha}`
- Produces: matching Project consults `git_ls_remote(project.git_url, project.git_ref)`; enqueue sha is that return value, never the planted `sha`

- [ ] **Step 1: Write the failing tests**

Replace `_boom_ls_remote` with an injectable head map. Keep boom only where enqueue must **not** call git (unknown type can keep a silent fake).

```python
EVIL_SHA = "ccc333evil"


def _inject_ls_remote(monkeypatch, heads=None):
    """T1 git host. enqueue_git_push must consult this, not the planted sha."""
    from deploys import poller as git_poller

    mapping = dict(heads or {(GIT_URL, "main"): NEW_SHA})
    calls = []

    def fake(url, ref):
        calls.append((url, ref))
        return mapping.get((url, ref), "")

    monkeypatch.setattr(git_poller, "git_ls_remote", fake)
    return calls
```

Change `_poll` to call `_inject_ls_remote` instead of `_boom_ls_remote`.

Add:

```python
@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_git_push_planted_sha_is_not_the_head(monkeypatch):
    """A planted historical SHA must not become Manifest.git_sha.

    What would make this fail: enqueue_git_push substituting the planted
    sha as ls_remote, or never calling git_ls_remote for a matching Project.
    """
    from monitor.intake_poll import FakeIntakeClient, poll

    queued = _patch_delay(monkeypatch)
    site = _git_site(slug="git-wakeup")
    calls = _inject_ls_remote(monkeypatch, heads={(GIT_URL, "main"): NEW_SHA})
    client = FakeIntakeClient()
    client.plant_git_push(GIT_URL, "main", EVIL_SHA, job_id="git-evil")
    result = poll(client=client, jitter=0, sleep=lambda _s: None)
    assert result["ok"] is True
    assert (GIT_URL, "main") in calls
    created = Deployment.objects.get(pk=queued[0])
    assert created.manifest.body["git_sha"] == NEW_SHA
    assert created.manifest.body["git_sha"] != EVIL_SHA
    assert created.manifest.version == 2


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_git_push_wake_up_when_remote_unchanged_does_not_enqueue(monkeypatch):
    """Wake-up with git-host sha already deployed creates no new Deployment.

    What would make this fail: using the planted sha as a new head when
    ls_remote still returns the last deployed sha.
    """
    from monitor.intake_poll import FakeIntakeClient, poll

    queued = _patch_delay(monkeypatch)
    site = _git_site(slug="git-same-head")
    _inject_ls_remote(monkeypatch, heads={(GIT_URL, "main"): OLD_SHA})
    client = FakeIntakeClient()
    client.plant_git_push(GIT_URL, "main", EVIL_SHA, job_id="git-same")
    poll(client=client, jitter=0, sleep=lambda _s: None)
    assert queued == []
    assert Deployment.objects.filter(manifest__site=site).count() == 1
```

Rewrite `test_git_push_outbox_enqueues_deploy` docstring: Hub **does** consult `git_ls_remote` (injected). Assert `git_ls_remote` was called with `(GIT_URL, "main")` and the other repo was not. Keep `created.manifest.body["git_sha"] == NEW_SHA` **from the injected head**, not because the plant was `NEW_SHA` (plant `NEW_SHA` is still fine here if the inject returns the same; the evil test is the tooth).

Keep `test_git_url_goes_through_validate_git_url`, public-route 404s, no-secret, run-twice, drain pin. Run-twice still plants `NEW_SHA` and injects head `NEW_SHA`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/j/j/deploy-hub/.venv/bin/pytest tests/test_git_webhook_outbox.py::test_git_push_planted_sha_is_not_the_head tests/test_git_webhook_outbox.py::test_git_push_wake_up_when_remote_unchanged_does_not_enqueue -q`

Expected: FAIL — planted `EVIL_SHA` is today's `ls_remote` return, so first test gets `git_sha == EVIL_SHA`; second test enqueues `EVIL_SHA`.

- [ ] **Step 3: Minimal implementation**

In `deploys/poller.py` `enqueue_git_push`:

```python
def enqueue_git_push(git_url, ref, sha, *, now=None, in_window=None, ls_remote=None):
    """Wake the git poller for matching Projects. Planted sha is not the head."""
    validate_git_url(git_url, resolve=False)
    hint_url, hint_ref = git_url, ref
    used = git_ls_remote if ls_remote is None else ls_remote

    def lookup(url, remote_ref):
        if url == hint_url and remote_ref == hint_ref:
            return used(url, remote_ref)
        return ""

    poll(ls_remote=lookup, now=now, in_window=in_window)
```

Do **not** `return sha` from `lookup`. Do not call `used` for non-matching Project urls. Keep `validate_git_url` before `poll`. Do not change `git_ls_remote` argv isolation. Do not import `intake`.

Optional kwarg `ls_remote=` is for tests that call `enqueue_git_push` directly; Fake-poller tests patch `git_ls_remote`.

- [ ] **Step 4: Run**

Run: `/Users/j/j/deploy-hub/.venv/bin/pytest tests/test_git_webhook_outbox.py tests/test_git_poller.py -q`

Expected: PASS. Neighbors: no Hub inbound, six K3 families, no intake secret, drain pin, flag-off git-push still acked.

- [ ] **Step 5: Commit**

```bash
git add deploys/poller.py tests/test_git_webhook_outbox.py
git commit -m "$(cat <<'EOF'
A planted git-push SHA was treated as ls-remote, so a compromised intake could roll an operator site back.

enqueue_git_push still validates the untrusted URL, then asks git_ls_remote
only for matching Project.git_url+git_ref. The git host is the head.
EOF
)"
```
