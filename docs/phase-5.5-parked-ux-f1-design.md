# Phase 5.5 parked UX F1 — destination-order picker

Not a new phase. Next honest §I line after Security F2 (`766d2d0`):
MUST-panel UX F1 (Minor). Not U1, not Phase 6, not Architect F1
`core → deploys`.

**Branch:** `p55-ux-f1` cut from master `766d2d0`.
**Spec:** `docs/phase-5.5-design-note.md` r2 C8/C5/D-082; MUST UX F1
(`.superpowers/sdd/phase-5.5-tasks/phase-5.5-must-ux.md`).

## Lands

Settings Partners can **add / reorder / remove** destinations, then T2
`partner.destination_rank` POSTs that list through the existing
`POST /api/v1/partners/<pk>/destination-rank/` path.

1. GET `/api/v1/partners/` grows `candidate_targets`: READY `Target` rows
   `{id, host, kind, tunnel}` (`tunnel` = `collect_payload.tunnel is True`).
   No `Site.tier` / `Target.tier`. No new route. No Hub `/api/partner/*`.
2. PartnersPanel keeps a per-partner **draft** order (starts as stored
   `destination_order`). Add from candidates not already in the draft;
   Up / Down / Remove. Rank posts **the draft**, not the stored list.
3. Confirm `summary` is the K5 honesty sentence **iff the draft includes
   `kind=ssh`**, else “Default: dedicated cloud first.” Empty-order copy
   stays “partner-site create will refuse.”
4. Own-server without tunnel still 400 + Finding on POST (existing).
   Picker may list those targets; save still refuses.

NAV stays six. No picker on a 7th NAV or a new phone screen. Copy: partner
site / partner-tier target, never “instance.” Never Connected. T2 ConfirmDialog,
not a toggle / T1 overlay.

## Does not land

U1 / `named-partner.md` stub / invented tokens. HMAC/MCP. Architect F1
cycle / `0013`. Live CF-for-SaaS. Co-host / Hub-host refuse at rank time
(still materialize-time). New registry ids.

## Exit

One green `make review-round` + conformance-5 minus live. Five-seat MERGE
(or MERGE-AFTER-FIXES + scoped re-review). Panel vote is the merge click.
