# Phase 7.1 Design Note — Router Advisor (one probe)

**Phase:** 7.1 per addendum §E9 / §I Phase 7 (Router Advisor) and plan §7.1.1
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r1 — tunnel "verify nothing forwarded" only. Binding §7.
**Estimate:** hours. Protective cut: **D-125**. Phase 7.0 T1 restore is on `master` after the 7.0 gate. Preview environments, LAN ghosts, Pulumi/managed-DB/LB, Azure, overwrite-live restore, HMAC, U1, live AWS, model-tailored UPnP/WPS/VLAN steps are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. No new `CheckRun.Kind`. No new Target columns. Finding only (`router-forwarded:{pk}`).
**Panel:** §7 is binding. Expert team continue (Joseph delegated commit/merge/push).

## 1. What lands this wave

Addendum §E9 recut Router Advisor: Tunnel mode makes the router story **"verify nothing is forwarded" — one probe, not a feature**. Plan §7.1.1's model-tailored steps, UPnP automation, WAN-admin/WPS hygiene, and VLAN/DMZ stay later. F1 already says Router advice is a **tab on Target detail**, not a seventh NAV item.

This wave adds that one probe and the Target-detail Router tab. It does **not** scan a live WAN, talk UPnP/SSDP, or rewrite a home router.

### 1.1 MUST

1. **One probe.** `monitor/router_advisor.py::probe_nothing_forwarded(target, *, wan_probe=None)` runs only when `collect_payload.tunnel is True`. `wan_probe()` returns `{"forwards": [{"port": int, "proto": "tcp"|"udp"}, ...]}`. Any forward → file Finding `source_engine=router_advisor`, fingerprint `router-forwarded:{target.pk}`, severity P2, entity `target:{pk}`, §6.6 copy (what / why / exact fix). Zero forwards → `resolve()` that fingerprint when OPEN/ACKED. Missing inject → do **not** file (no false alarm); POST returns 4xx `wan probe refused`. Non-tunnel targets skip (no Finding). Default `wan_probe` is refuse-closed (no socket, no UPnP, no subprocess).

2. **HTTP.** New module `monitor/router_views.py` (do **not** fold into `core/views.py`). `GET /api/v1/targets/` list `{id, host, kind, tunnel}`. `GET /api/v1/targets/{id}/` detail adds `router_advice` `{mode, forwarded, finding_id, title, body}`. `POST /api/v1/targets/{id}/router-probe/` T3 `target.router_probe` label exactly `Probe router`. Serializer empty (`{}`). 201 `{ok: true, target_id, forwarded, finding_id}`. Tests inject `wan_probe=` via wrapping the view's callee. `make generate-client`. ACTION_TIERS `{id: "target.router_probe", tier: "T3", label: "Probe router", undo_window_s: 10}`. Not T1 — do not add to `T1_HTTP`.

3. **Target detail tabs.** `#/targets/{id}` already parses. `App.jsx` passes `route` / `onNav` into `Targets`. List rows navigate to the id. Detail tabs **Hardening** | **Router**. Hardening copy is honest: hardening findings stay in the Findings inbox. Router tab renders `router_advice` (icon+label, not color-only), links `#/findings/{id}` when `finding_id` is set, and the T3 ActionButton. NAV stays six. Do not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`.

4. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST ids phase 7, tier-less. `conformance-7` stays the phase gate and is **not** a review-round/nightly prereq. Do not waive U1. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO` or `P7-RESTORE-DEMO` on new pytest. Claim `monitor/router_advisor.py` and `monitor/router_views.py` in `paths.yaml` + CODEOWNERS (do not broaden `monitor/**` or `frontend/**`). AST-scan the new modules: no `subprocess`, no `socket.create_connection`, no `upnp`/`ssdp`/`minissdp` imports.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| Tunnel-mode probe: nothing forwarded; Finding on any WAN map | **MUST** |
| Target list + detail Router tab + T3 Probe router | **MUST** |
| Default wan_probe refuse-closed; inject in tests | **MUST** |
| Model-tailored steps / UPnP off / WPS / WAN admin / firmware / VLAN | **OUT** |
| Fallback DHCP reservation + 80/443 forwards | **OUT** |
| Preview envs / LAN ghosts / Pulumi / Azure / overwrite-live | **OUT** |
| U1 / HMAC / live AWS | Unchanged park |

## 2. Interfaces that change

**Python:** `monitor/router_advisor.py` (new). `monitor/router_views.py` (new). `monitor/urls.py`. `core/actions.py` ACTION_TIERS. Frontend `Targets.jsx` + `App.jsx` route pass. `frontend/tests/targets.test.ts`. Acceptance NAMED in `tests/acceptance/test_phase_7.py`. Append `conformance/demos/phase-7.md`.

**Not changed:** `monitor/topology.py` product. `core/views.py`. CheckRun kinds. Beat schedule (no weekly drift job this wave — E9 is one probe, not a feature). Evaluator / overflow. Findings.jsx / Chrome.jsx / seed. No schema.

## 3. Applicable registry reqs

Task 0 — new MUST ids, phase 7, no `tier:`. `source: phase-7.1-design-note.md §3`. Compute `text_hash:` via `--print-text-hashes`. Extend `PHASE_7_MUST_IDS` + `allowed_sources`. `PHASE_7_TEST_IDS` subtracts both demo ids.

- `ROUTER-TUNNEL-NOTHING-FORWARDED` — `phase: 7`, `verify: test`. `text:` Tunnel-mode Target (collect_payload.tunnel true) probe_nothing_forwarded files Finding router-forwarded:{pk} when wan_probe reports any WAN forward and resolves that fingerprint when forwards is empty; missing wan_probe does not file; non-tunnel targets skip; default wan_probe is refuse-closed.
- `ROUTER-ADVICE-TARGET-TAB` — `phase: 7`, `verify: test`. `text:` GET /api/v1/targets/{id}/ returns router_advice; Targets detail has Hardening and Router tabs; Router tab renders the advice and T3 Probe router; NAV stays six; no color-only status.
- `P7-ROUTER-DEMO` — `phase: 7`, `verify: demo`, `demo: conformance/demos/phase-7.md`.

## 4. Exit demo

Tunnel-mode SSH target, injected `wan_probe` returning one `{port: 443, proto: tcp}` → Finding OPEN `router-forwarded:{pk}`; GET detail `router_advice.finding_id` set; T3 POST probe with empty forwards → Finding RESOLVED; GET detail `finding_id` null. Missing inject → 4xx, no Finding. Non-tunnel target → no Finding. Record: append `conformance/demos/phase-7.md`. Honest: no live UPnP, no live WAN scan, no model-tailored steps, no preview, no LAN ghosts, no U1.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-125** Protective cut — one tunnel probe ("verify nothing forwarded") + Target-detail Router tab + T3 Probe router. §7.1.1 hygiene/automation/VLAN and fallback 80/443 forwards are later. Preview / LAN / Pulumi / Azure stay later.
- **D-126** Finding-only (`router-forwarded:{pk}`, P2). No new CheckRun.Kind. Default `wan_probe` refuse-closed; tests inject. HTTP lives in `monitor/router_views.py`, not `core/views.py`.
- **D-127** Everyday gates stay phase 5 minus live. New ids phase 7 tier-less. `conformance-7` stays the phase gate and is not a review-round prereq. U1 stays uncovered. Claim the two new monitor modules only.

## 6. Protective cut (D-125)

MUST = tunnel nothing-forwarded probe + Finding + Target list/detail Router tab + T3 + registry. Model-tailored router feature, preview, LAN ghosts, Pulumi, Azure, U1 are **OUT**.

## 7. Closed contract (binding)

**C1 Probe.** `collect_payload.tunnel is True` only. `wan_probe()` shape is exactly `{forwards: [{port: int, proto: "tcp"|"udp"}]}`. Any non-empty forwards → file/refresh. Empty forwards → resolve OPEN/ACKED. ACCEPTED stays until the operator resolves (same fingerprint must not become a second row). Missing `wan_probe` → no Finding.

**C2 Copy.** Title exactly `Tunnel target has a WAN forward`. Body names the port/proto and says a forwarded port bypasses Cloudflare Tunnel. `fix_action` exactly `Remove the WAN port mapping on the router, then Probe router.` No `\binstance\b` except existing tokens.

**C3 HTTP.** List + detail + T3 POST. Label exactly `Probe router`. View never binds a WAN scan from the request body. generate-client. 4xx on missing inject / non-tunnel POST (`not tunnel mode`).

**C4 Tabs.** Hardening | Router. Hardening does not invent a hardening engine. Router tab has `data-tab="router"`. Finding link is `#/findings/{id}`. App passes `route`.

**C5 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P6-SCALER-DEMO` or `P7-RESTORE-DEMO` or `P7-ROUTER-DEMO` on pytest.

**C6 Registry.** Task 0 adds the three ids, extends `PHASE_7_MUST_IDS` + `allowed_sources` with `phase-7.1-design-note.md §3`. Do not rewrite Phase 7.0 `text:`. Do not claim `core/views.py` / `monitor/topology.py` / `frontend/**`.

**C7 Module arrows.** `monitor/router_advisor.py` may import `core.findings` + `core.models.Finding`/`Target`. It must not import `deploys`, `providers`, `vault`. `router_views.py` → `router_advisor`. AST forbids `subprocess`, `socket.create_connection`, `upnp`, `ssdp`.

**C8 Gate.** `python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3` verifies the new ids; U1 uncovered-only allowed.
