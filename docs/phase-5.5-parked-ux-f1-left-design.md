# Phase 5.5 parked UX F1 leftovers — Rank honesty pins

Not a new phase. Next honest §I line after Architect F1 (`4f6ec26`):
the three UX F1 merge leftovers. Not U1, not Phase 6, not Azure.

**Branch:** `p55-ux-f1-left` cut from master `4f6ec26`.
**Spec:** `docs/phase-5.5-parked-ux-f1-design.md` Lands 3; whole-branch
final-review deferred minors.

## Lands

1. One honesty source. Delete unused `rankSummary` (it still keys on
   stored `destinations`). Rank `ActionButton.props.summary` stays the
   draft lookup: `kind === "ssh"` from `destinations ∪ candidateTargets`,
   including `tunnel: false`.
2. Named pin: stored empty destinations + draft ssh `tunnel: false` →
   Rank summary matches `/abuse takedowns/`. Do not key honesty on
   `tunnel`.
3. Named pin: picker markup has no `type="checkbox"` / `role="switch"`
   (select + buttons only).

NAV six. T2 ConfirmDialog. No new URL. Rank POST unchanged.

## Does not land

U1 / `named-partner.md` stub / invented tokens. HMAC/MCP. Phase 6.
Azure. Architect F1 reopen. Live CF-for-SaaS. New registry ids.

## Exit

One green `make review-round` + conformance-5 minus live. Five-seat
MERGE. Panel vote is the merge click.
