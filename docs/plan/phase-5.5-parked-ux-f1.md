# Phase 5.5 parked UX F1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** An operator can add/reorder partner destinations on Settings Partners and T2-save a new `destination_order`.

**Architecture:** List GET grows READY `candidate_targets`. PartnersPanel drafts an order locally and POSTs it through existing `rankPartnerDestination`.

**Tech Stack:** Django, pytest, React, node:test.

**Spec:** `docs/phase-5.5-parked-ux-f1-design.md`

## Global Constraints

- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. No `t4`.
- Do not invent `HUB_TEST_*` tokens. Do not stub `named-partner.md`. HMAC uneabled. MCP OUT. No `Site.tier`.
- Function-level `@pytest.mark.req("UX-P55-PARTNERS")` only. No new registry ids. Do not edit `REVIEW_CHECKLIST.md` / `conformance/requirements.yaml`.
- NAV six. Create partner not Connect. Never Connected / instance. T2 rank, not T1 overlay.
- TDD. Long why HEREDOC commits. Work on `p55-ux-f1`, never master.

## File map

| File | Tasks |
|---|---|
| `core/partner_views.py` | Task 1 |
| `tests/test_partner_create.py` | Task 1 |
| `frontend/src/screens/Settings.jsx` | Task 2 |
| `frontend/tests/settings-partners.test.ts` | Task 2 |

Task 1 then Task 2.

---

### Task 1: GET partners lists READY candidate_targets

**Files:**
- Modify: `core/partner_views.py` (`PartnerListSerializer`, `_intake_payload` neighbor GET)
- Test: `tests/test_partner_create.py`

**Interfaces:**
- Consumes: `Target.Status.READY`, `collect_payload`
- Produces: GET `/api/v1/partners/` JSON key `candidate_targets`: list of `{id, host, kind, tunnel}` (tunnel bool). PENDING/ERROR/DECOMMISSIONED omitted.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.req("UX-P55-PARTNERS")
def test_partners_list_includes_ready_candidate_targets(client):
    """GET /api/v1/partners/ lists READY targets for the rank picker.

    What would make this fail: omitting candidate_targets, including a
    pending target, dumping collect_payload / ssh_key_ref onto the list,
    or omitting tunnel so the picker cannot see ssh-without-tunnel.
    """
    from core.models import NetworkZone, Partner, Target
    from core.partner_views import PartnerListCreateView
    from rest_framework.test import APIRequestFactory

    _t1_user(client)
    zone = NetworkZone.objects.create(name="cand-z", slug="cand-z")
    ready = Target.objects.create(
        zone=zone, host="cloud.cand.test", kind=Target.Kind.AWS_EC2,
        status=Target.Status.READY,
    )
    ssh = Target.objects.create(
        zone=zone, host="home.cand.test", kind=Target.Kind.SSH,
        status=Target.Status.READY,
        ssh_key_ref="planted-ssh-key-ref-ux-f1",
        host_key_fingerprint="SHA256:planted-host-key-fp-ux-f1",
        collect_payload={
            "tunnel": True,
            "hubk_test_leak": "nope",
            "whsec_leak": "nope",
            "log_chunk": {"bytes": "secret-bytes"},
        },
    )
    pending = Target.objects.create(
        zone=zone, host="pending.cand.test", kind=Target.Kind.AWS_EC2,
        status=Target.Status.PENDING,
    )
    errored = Target.objects.create(
        zone=zone, host="error.cand.test", kind=Target.Kind.AWS_EC2,
        status=Target.Status.ERROR,
    )
    gone = Target.objects.create(
        zone=zone, host="gone.cand.test", kind=Target.Kind.AWS_EC2,
        status=Target.Status.DECOMMISSIONED,
    )
    open_ssh = Target.objects.create(
        zone=zone, host="open.cand.test", kind=Target.Kind.SSH,
        status=Target.Status.READY, collect_payload={"tunnel": False},
    )
    empty = Partner.objects.create(slug="cand-empty", name="cand-empty")
    assert empty.destination_order == []
    view = PartnerListCreateView()
    view.request = APIRequestFactory().get(CREATE_URL)
    assert [type(p).__name__ for p in view.get_permissions()] == ["IsAuthenticated"]
    response = client.get(CREATE_URL)
    assert response.status_code == 200
    body = response.json()
    dumped = _blob(body)
    assert "hubk_" not in dumped
    assert "whsec_" not in dumped
    assert "ssh_key_ref" not in dumped
    assert "host_key_fingerprint" not in dumped
    assert "secret-bytes" not in dumped
    assert "log_chunk" not in dumped
    assert "hubk_test_leak" not in dumped
    assert "whsec_leak" not in dumped
    assert "planted-ssh-key-ref-ux-f1" not in dumped
    assert "SHA256:planted-host-key-fp-ux-f1" not in dumped
    cands = body["candidate_targets"]
    ids = {row["id"] for row in cands}
    assert ready.pk in ids
    assert ssh.pk in ids
    assert pending.pk not in ids
    assert errored.pk not in ids
    assert gone.pk not in ids
    for row in cands:
        assert set(row) == {"id", "host", "kind", "tunnel"}
    ssh_row = next(row for row in cands if row["id"] == ssh.pk)
    assert ssh_row["host"] == "home.cand.test"
    assert ssh_row["kind"] == Target.Kind.SSH
    assert ssh_row["tunnel"] is True
    cloud_row = next(row for row in cands if row["id"] == ready.pk)
    assert cloud_row["tunnel"] is False
    open_row = next(row for row in cands if row["id"] == open_ssh.pk)
    assert open_row["tunnel"] is False
    listed = next(row for row in body["partners"] if row["slug"] == "cand-empty")
    assert listed["destination_order"] == []
    assert "candidate_targets" not in listed
    detail = client.get(f"{CREATE_URL}{empty.pk}/")
    assert detail.status_code == 200
    assert "candidate_targets" not in detail.json()
```

- [ ] **Step 2: Run to verify RED**

`/Users/j/j/deploy-hub/.venv/bin/pytest tests/test_partner_create.py::test_partners_list_includes_ready_candidate_targets -q`

Expected: FAIL (`candidate_targets` KeyError).

- [ ] **Step 3: Minimal implementation**

Add `CandidateTargetSerializer` (`id`, `host`, `kind`, `tunnel`). Add field on `PartnerListSerializer`. Helper:

```python
def _candidate_targets():
    from core.models import Target
    out = []
    for row in Target.objects.filter(status=Target.Status.READY).order_by("pk"):
        payload = row.collect_payload or {}
        out.append({
            "id": row.pk,
            "host": row.host,
            "kind": row.kind,
            "tunnel": payload.get("tunnel") is True,
        })
    return out
```

GET list includes `"candidate_targets": _candidate_targets()` on the **list envelope** (`PartnerListSerializer`), never on `PartnerPublic` / `PartnerDetailView`. Do not add a new URL. Do not change `PartnerDestinationRankView`. Helper stays four explicit keys (`id`, `host`, `kind`, `tunnel`); `status=Target.Status.READY`; `payload.get("tunnel") is True`. Do **not** `{**payload}` and do **not** `ModelSerializer(Target)`. Keep `PartnerListCreateView.get_permissions` GET/HEAD/OPTIONS → `[IsAuthenticated()]`. Do not put `RequireRecentTouch` back on GET (`_t1_user` is not that pin). GET must not insert a CheckRun.

If spectacular/OpenAPI drifts, run `make generate-client` and commit generated client files (D-002). Do not edit `REVIEW_CHECKLIST.md`.

- [ ] **Step 4:** `/Users/j/j/deploy-hub/.venv/bin/pytest tests/test_partner_create.py tests/test_partner_isolation.py::test_empty_destination_order_refuses_create tests/test_partner_kill_switch.py::test_destination_rank_http_pin_and_own_server_honesty_sentence -q` PASS. Rank path still `PartnerDestinationRankView`; ssh-without-tunnel POST still 400 + Finding.

- [ ] **Step 5: Commit**

```bash
git add core/partner_views.py tests/test_partner_create.py
git commit -m "$(cat <<'EOF'
Settings Partners had no fleet of READY targets, so rank could only re-save an empty order.

GET /api/v1/partners/ now lists candidate_targets with host, kind, and tunnel
so the picker can add destinations the stored order does not yet contain.
EOF
)"
```

---

### Task 2: PartnersPanel drafts and POSTs a new order

**Files:**
- Modify: `frontend/src/screens/Settings.jsx`
- Test: `frontend/tests/settings-partners.test.ts`

**Interfaces:**
- Consumes: Task 1 `candidate_targets`; `rankPartnerDestination(id, order)`
- Produces: exported `addDestination` / `moveDestination` / `removeDestination`; Rank posts draft ids; honesty iff draft has `kind=ssh`

- [ ] **Step 1: Write failing tests** in `frontend/tests/settings-partners.test.ts`

```typescript
import {
  addDestination, moveDestination, removeDestination, rankSummary,
} from "../src/screens/Settings.jsx";

test("rank_draft_helpers_add_reorder_remove", () => {
  assert.deepEqual(addDestination([], 2), [2]);
  assert.deepEqual(addDestination([2], 2), [2]);
  assert.deepEqual(moveDestination([1, 2, 3], 3, -1), [1, 3, 2]);
  assert.deepEqual(moveDestination([1, 2], 1, -1), [1, 2]);
  assert.deepEqual(removeDestination([1, 2], 1), [2]);
});

test("ranker_posts_draft_order_not_stored_empty", async () => {
  const CANDS = [
    { id: 7, host: "cloud.rank.test", kind: "aws_ec2", tunnel: false },
    { id: 8, host: "home.rank.test", kind: "ssh", tunnel: true },
  ];
  const markup = render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
      destinations: [], suspended: false }],
    intake: { status: "degraded", mode: "fake", configured: false },
    candidateTargets: CANDS,
    rankDrafts: { 1: [7, 8] },
  });
  const text = visibleText(markup);
  assert.match(text, /cloud.rank.test/);
  assert.match(text, /home.rank.test/);
  assert.match(text, /Add destination/);
  assert.doesNotMatch(text, /\bConnected\b/);
  assert.doesNotMatch(text, /\binstance\b/i);

  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const { act, create } = await import("react-test-renderer");
  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return { status: 200, json: async () => ({ id: 1, slug: "fixture-partner",
      destination_order: [7, 8], destinations: CANDS }) };
  };
  let tree: any;
  act(() => {
    tree = create(React.createElement(PartnersPanel, {
      partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
        destinations: [], suspended: false }],
      intake: { status: "degraded", mode: "fake", configured: false },
      candidateTargets: CANDS,
      rankDrafts: { 1: [7, 8] },
    }));
  });
  const rankBtn = tree.root.findAllByType(ActionButton)
    .find((n: any) => n.props.row.id === "partner.destination_rank");
  assert.ok(rankBtn);
  assert.match(String(rankBtn.props.summary), /abuse takedowns/);
  await rankBtn.props.onRun();
  const posted = calls.find((c) => String(c.url).includes("destination-rank"));
  assert.ok(posted, "Rank must POST destination-rank");
  assert.deepEqual(posted.body.destination_order, [7, 8]);
  act(() => { tree.unmount(); });
});
```

Keep `ranker_own_server_honesty_sentence_and_never_connected` green.

- [ ] **Step 2: Run RED**

`cd frontend && node --import tsx --test tests/settings-partners.test.ts`

Expected: FAIL (exports missing / Add destination absent).

- [ ] **Step 3: Minimal implementation**

```javascript
export function addDestination(order, targetId) {
  const id = Number(targetId);
  if (!id || (order || []).includes(id)) return list(order);
  return [...list(order), id];
}
export function moveDestination(order, targetId, dir) {
  const next = list(order);
  const i = next.indexOf(Number(targetId));
  const j = i + Number(dir);
  if (i < 0 || j < 0 || j >= next.length) return next;
  const copy = next.slice();
  const [row] = copy.splice(i, 1);
  copy.splice(j, 0, row);
  return copy;
}
export function removeDestination(order, targetId) {
  return list(order).filter((id) => id !== Number(targetId));
}
function list(order) { return Array.isArray(order) ? order.slice() : []; }
```

`PartnersPanel` accepts `candidateTargets` / `rankDrafts` props (tests). Live fetch reads `data.candidate_targets`. Per-partner draft state defaults to `destination_order`. Rank:

```javascript
async function runRank(partner) {
  const order = drafts[partner.id] || partner.destination_order || [];
  await rankPartnerDestination(partner.id, order);
  await refreshList();
}
```

Honesty / ActionButton `summary` uses draft destinations (lookup `kind` from `destinations` ∪ `candidateTargets`), including when stored `destinations` is empty. ssh-without-tunnel in the draft still counts as `kind=ssh` (honesty); POST still 400. UI: for each draft id, show host + Up + Down + Remove. `<select aria-label="Add destination">` of candidates not in draft + button “Add destination”. Empty copy unchanged. No checkbox/switch. No 7th NAV. Skip live `partnersList()` fetch when `partners` prop is injected. Default `candidateTargets`/`rankDrafts` so F8 `partner-destination-order-confirm` still mounts.

- [ ] **Step 4:** `cd frontend && node --import tsx --test tests/settings-partners.test.ts tests/simulation-states.test.ts` plus pytest honesty/create neighbors PASS. Rank stays T2 ConfirmDialog.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/Settings.jsx frontend/tests/settings-partners.test.ts
git commit -m "$(cat <<'EOF'
Rank still posted the stored empty destination_order, so the tab could not add a target.

PartnersPanel drafts add/reorder/remove against READY candidates and T2-saves
that list. Honesty still fires only when the draft includes kind=ssh.
EOF
)"
```
