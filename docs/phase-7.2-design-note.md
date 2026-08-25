# Phase 7.2 Design Note — LAN discovery ghost view

**Phase:** 7.2 per addendum §I Phase 7 (LAN discovery ghost view) and plan §9.6.2 Map
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r1 — optional injected ghosts only. Binding §7.
**Estimate:** hours. Protective cut: **D-128**. Phase 7.1 Router Advisor is on `master` @ `d6cb727`. Preview environments, Pulumi/managed-DB/LB, Azure, overwrite-live, HMAC, U1, live nmap are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. No new Target columns. No new Finding engine (ghosts are map nodes, not Findings).
**Panel:** §7 is binding. Expert team continue (Joseph delegated commit/merge/push).

## 1. What lands this wave

Plan map: "optional LAN discovery ghosts." Hosts seen on the LAN that are **not** enrolled Targets render as ghost nodes on the fleet map. This wave is the view + inject seam. It does **not** run nmap, mdns, or ARP in T1.

### 1.1 MUST

1. **Inject seam.** `monitor/lan_ghosts.py::attach_lan_ghosts(nodes, targets, *, lan_scan=None)` — `lan_scan()` returns `[{"host": str, "zone_id": int|null}]`. Skip any `host` that already equals an enrolled `Target.host` (case-sensitive, as stored). Append `{id: "ghost:{host}", kind: "ghost", label: host, status: "ghost", parent: "zone:{zone_id}" if zone_id else omitted}`. `lan_scan is None` → return nodes unchanged. Default refuse-closed.

2. **Snapshot.** `monitor/map_graph.py::graph_snapshot` calls `attach_lan_ghosts` after `_derive` and before `attach_findings`. `_NODE_KINDS` gains `ghost`. Tests inject `lan_scan=` by wrapping `monitor.map_graph.attach_lan_ghosts` or the snapshot callee. Do **not** claim `monitor/map_graph.py` wholesale.

3. **Serializer + map.** `MapNodeSerializer.kind` choices gain `ghost`. `make generate-client`. `Map.jsx`: `STATUS_ICON.ghost = "◌"`; `data-kind="ghost"` already flows from the generic node renderer; layout places ghosts under their parent zone (same as hosts) or in a fallback column if no parent. List view shows the ghost label + icon+label status (not color-only). NAV six. Do not edit Findings.jsx / Chrome.jsx.

4. **Honesty / gates.** Everyday `conformance` stays `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST ids phase 7, tier-less. `conformance-7` stays the phase gate. Do not waive U1. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO` / `P7-RESTORE-DEMO` / `P7-ROUTER-DEMO` on new pytest. Claim `monitor/lan_ghosts.py` only. AST: no `subprocess`, no `nmap`, `scapy`, `mdns`, `zeroconf`.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| Injected LAN ghosts on the map; skip enrolled hosts | **MUST** |
| Default lan_scan refuse-closed | **MUST** |
| Live nmap / mDNS / ARP / T3 Scan LAN | **OUT** |
| Preview envs / Pulumi / Azure | **OUT** |
| U1 / HMAC / live AWS | Unchanged park |

## 2. Interfaces that change

**Python:** `monitor/lan_ghosts.py` (new). One call from `map_graph.graph_snapshot`. `MapNodeSerializer` kind choices. Frontend `Map.jsx` STATUS_ICON + layout. `frontend/tests/map.test.ts`. Acceptance NAMED in `tests/acceptance/test_phase_7.py`. Append `conformance/demos/phase-7.md`.

**Not changed:** topology rules r1–r5. Router Advisor. ACTION_TIERS. Beat. Findings.jsx / Chrome.jsx / seed. No schema. No new HTTP route (GET map already exists).

## 3. Applicable registry reqs

Task 0 — new MUST ids, phase 7, no `tier:`. `source: phase-7.2-design-note.md §3`. Compute `text_hash:` via `--print-text-hashes`. Extend `PHASE_7_MUST_IDS` + `allowed_sources`. Subtract `P7-LAN-GHOST-DEMO` from `PHASE_7_TEST_IDS`.

- `LAN-GHOST-INJECT` — `phase: 7`, `verify: test`. `text:` attach_lan_ghosts appends kind=ghost nodes for lan_scan hosts that are not enrolled Target.host and skips enrolled hosts; lan_scan None leaves the graph unchanged; default is refuse-closed.
- `LAN-GHOST-MAP-VIEW` — `phase: 7`, `verify: test`. `text:` GET map snapshot serializes kind=ghost; Map list and SVG render ghost with icon+label status not color-only; NAV stays six.
- `P7-LAN-GHOST-DEMO` — `phase: 7`, `verify: demo`, `demo: conformance/demos/phase-7.md`.

## 4. Exit demo

Zone + enrolled target `web-1`, injected `lan_scan` returning `web-1` and `printer.lan` → snapshot has one ghost `ghost:printer.lan` and no `ghost:web-1`. `lan_scan=None` → no ghost kinds. Map list/SVG show `◌ ghost` + `printer.lan`. Record: append `conformance/demos/phase-7.md`. Honest: no live nmap, no preview, no Azure, no U1.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-128** Protective cut — optional injected LAN ghosts on the map. Live discovery and T3 Scan LAN are later. Preview / Pulumi / Azure stay later.
- **D-129** New module `monitor/lan_ghosts.py`. `graph_snapshot` calls it. Do not claim `map_graph.py` wholesale. Ghosts are map nodes, not Findings.
- **D-130** Everyday gates stay phase 5 minus live. New ids phase 7 tier-less. `conformance-7` stays the phase gate. U1 stays uncovered. Claim `lan_ghosts.py` only.

## 6. Protective cut (D-128)

MUST = inject seam + ghost kind on snapshot/map + registry. Live scan, preview, Pulumi, Azure, U1 are **OUT**.

## 7. Closed contract (binding)

**C1 Inject.** `lan_scan()` shape is exactly `[{host: str, zone_id: int|null}]`. Skip enrolled `Target.host`. Id `ghost:{host}`. kind `ghost`. status `ghost`. Missing inject → no ghosts.

**C2 Copy.** Ghost label is the host. Status icon+label (`◌ ghost`). No `\binstance\b` except existing tokens.

**C3 HTTP.** No new route. GET `/api/v1/map/` already returns the snapshot. generate-client after kind enum grows.

**C4 Map.** `data-kind="ghost"`. List view includes the label. Empty fleet copy unchanged when there are no zones/hosts/ghosts.

**C5 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Do not mark demo ids on pytest.

**C6 Registry.** Task 0 adds the three ids, extends `PHASE_7_MUST_IDS` + `allowed_sources` with `phase-7.2-design-note.md §3`. Do not rewrite 7.0/7.1 `text:`.

**C7 Module arrows.** `lan_ghosts.py` may import Target. No `subprocess` / `nmap` / `scapy` / `mdns` / `zeroconf`. `map_graph` → `lan_ghosts`.

**C8 Gate.** `python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3` verifies the new ids; U1 uncovered-only allowed.
