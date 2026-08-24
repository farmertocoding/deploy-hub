# Phase 5.5 parked UX F1 leftovers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Rank Confirm honesty is one source, including tunnel-false ssh, and the picker is not a toggle.

**Architecture:** Delete unused `rankSummary`. Named ActionButton pin for `tunnel: false` ssh. Picker markup pin against checkbox/switch.

**Tech Stack:** React, node:test.

**Spec:** `docs/phase-5.5-parked-ux-f1-left-design.md`

## Global Constraints

- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. No `t4`.
- Do not invent `HUB_TEST_*` tokens. Do not stub `named-partner.md`. HMAC uneabled. MCP OUT. No `Site.tier`.
- No new registry ids. Do not edit `REVIEW_CHECKLIST.md` / `conformance/requirements.yaml`.
- NAV six. Never Connected / instance. T2 rank, not T1 overlay. Honesty on `kind === "ssh"`, not `tunnel`.
- TDD. Long why HEREDOC commits. Work on `p55-ux-f1-left`, never master.

## File map

| File | Tasks |
|---|---|
| `frontend/src/screens/Settings.jsx` | Task 1 |
| `frontend/tests/settings-partners.test.ts` | Task 1 |

One task.

---

### Task 1: Draft honesty pin + drop leftover helper

**Files:**
- Modify: `frontend/src/screens/Settings.jsx`
- Test: `frontend/tests/settings-partners.test.ts`

**Interfaces:**
- Consumes: existing `destLookup` / Rank `ActionButton` / `candidateTargets`
- Produces: no `rankSummary` export; named tunnel-false honesty pin; picker `doesNotMatch` checkbox/switch

- [ ] **Step 1: Write the failing tests** in `frontend/tests/settings-partners.test.ts`

Remove `rankSummary` from the Settings import.

Keep `ranker_posts_draft_order_not_stored_empty` green. Add:

```typescript
test("ranker_open_ssh_draft_is_honesty_and_picker_is_not_a_toggle", async () => {
  const CANDS = [
    { id: 7, host: "cloud.rank.test", kind: "aws_ec2", tunnel: false },
    { id: 8, host: "open.rank.test", kind: "ssh", tunnel: false },
  ];
  const markup = render(PartnersPanel, {
    partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
      destinations: [], suspended: false }],
    intake: { status: "degraded", mode: "fake", configured: false },
    candidateTargets: CANDS,
    rankDrafts: { 1: [8] },
  });
  assert.doesNotMatch(markup, /type="checkbox"/);
  assert.doesNotMatch(markup, /role="switch"/);

  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const { act, create } = await import("react-test-renderer");
  let tree: any;
  act(() => {
    tree = create(React.createElement(PartnersPanel, {
      partners: [{ id: 1, slug: "fixture-partner", destination_order: [],
        destinations: [], suspended: false }],
      intake: { status: "degraded", mode: "fake", configured: false },
      candidateTargets: CANDS,
      rankDrafts: { 1: [8] },
    }));
  });
  const rankBtn = tree.root.findAllByType(ActionButton)
    .find((n: any) => n.props.row.id === "partner.destination_rank");
  assert.ok(rankBtn);
  assert.match(String(rankBtn.props.summary), /abuse takedowns/);
  act(() => { tree.unmount(); });
});
```

Add a source pin that `rankSummary` is gone:

```typescript
test("rank_summary_helper_is_gone", async () => {
  const src = await import("node:fs/promises");
  const text = await src.readFile(
    new URL("../src/screens/Settings.jsx", import.meta.url), "utf8",
  );
  assert.doesNotMatch(text, /export function rankSummary/);
});
```

- [ ] **Step 2: Run RED**

`cd frontend && node --import tsx --test tests/settings-partners.test.ts`

Expected: FAIL (`rankSummary` still exported; named CANDS ssh is `tunnel: true` so a tunnel-keyed summary still greens the old test; this new test uses `tunnel: false`).

- [ ] **Step 3: Minimal implementation**

Delete `export function rankSummary`. Keep Rank `ActionButton` summary on draft `kind === "ssh"` via `destLookup` (already on HEAD). Do not read `tunnel` for honesty. Do not add a checkbox/switch.

- [ ] **Step 4:** `cd frontend && node --import tsx --test tests/settings-partners.test.ts tests/simulation-states.test.ts` PASS. Keep `ranker_own_server_honesty_sentence_and_never_connected` and `ranker_posts_draft_order_not_stored_empty` green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/Settings.jsx frontend/tests/settings-partners.test.ts
git commit -m "$(cat <<'EOF'
Rank honesty still had a leftover helper on stored destinations, so a
tunnel-false ssh draft was unpinned.

The unused rankSummary export is gone. Confirm summary is the draft
kind=ssh lookup, including open ssh, and the picker is not a toggle.
EOF
)"
```
