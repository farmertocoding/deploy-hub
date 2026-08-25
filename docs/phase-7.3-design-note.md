# Phase 7.3 Design Note — Preview environments (private repos only)

**Phase:** 7.3 per addendum §I Phase 7 / §E9 parked line (preview environments, private repos only)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r1 — private-repo gate + Site row. Binding §7.
**Estimate:** hours-to-a-day. Protective cut: **D-131**. Phase 7.2 LAN ghosts are on `master` @ `005dcc3`. Pulumi/managed-DB/LB, Azure, live GitHub visibility, webhook PR builds, HMAC, U1 are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Schema:** `0015_phase73.py` adds `Site.preview_of` (FK self, null) and `Site.preview_ref` (CharField blank). `0014` stays closed otherwise. No ScalePolicy. No overflow FK.
**Panel:** §7 is binding. Expert team continue (Joseph delegated commit/merge/push).

## 1. What lands this wave

Dokploy's own docs warn PR authors can trigger builds on your server. The addendum parked previews until Phase 7 **and** restricted them to **private repos only**. This wave is that gate plus a mesh-only sibling Site. It does **not** auto-deploy, open a webhook, or ask GitHub.

### 1.1 MUST

1. **Gate.** `deploys/preview.py::create_preview(parent, ref, *, visibility=None)` — `ref` is a non-empty git ref (branch/tag/sha slug, max 128). `visibility is None` → `PreviewError("visibility refused")`. `visibility == "public"` → `PreviewError("public repo refused")`. Parent `project.source_kind != git` or empty `git_url` → `PreviewError("not a git project")`. `visibility == "private"` → create a Site: `name="preview-{parent.name}-{slug}"` (slug = ref safe chars), `exposure=mesh_only`, `preview_of=parent`, `preview_ref=ref`, same `project` and `primary_target`. Do **not** call `run_deploy` / poller / overflow. Copy no ciphertext.

2. **HTTP.** `deploys/preview_views.py` `POST /api/v1/sites/{id}/preview/` T2 `site.preview_create` label exactly `Create preview`. Serializer `{ref, confirm_name}` with `confirm_name == parent.name`. 201 `{ok: true, site_id, parent_id, ref}`. 4xx on the refuse reasons. Tests inject `visibility=` by wrapping the view's callee. `make generate-client`. ACTION_TIERS `{id: "site.preview_create", tier: "T2", label: "Create preview"}`. Not T1.

3. **Sites panel.** `Sites.jsx` SiteStatus / detail: T2 ActionButton `site.preview_create`. Summary names the parent and the ref. NAV six. Do not edit Findings.jsx / Chrome.jsx. Frontend test posts `/api/v1/sites/{id}/preview/`.

4. **Park (same Task 0).** Record D-134 Pulumi/managed-DB/LB = later if it grows (plan §7.2 / addendum §I). Record D-135 Azure adapter = when a workload needs it (review3 §V11). No product code.

5. **Honesty / gates.** Everyday `conformance` stays phase 5 minus live. New MUST ids phase 7, tier-less. `conformance-7` stays the phase gate. Do not waive U1. Do not stub `named-partner.md`. Do not mark demo ids on pytest. Claim `deploys/preview.py` + `deploys/preview_views.py` only. AST: no webhook route, no `HUB_WEBHOOK_SECRET`, no GitHub HTTP client.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| Private-only create_preview + mesh-only sibling Site | **MUST** |
| T2 Create preview on Sites | **MUST** |
| Auto-deploy the preview / PR webhook / live GitHub visibility | **OUT** |
| Pulumi / managed-DB / LB | **PARK** (D-134) |
| Azure adapter | **PARK** (D-135) |
| U1 / HMAC / live AWS | Unchanged park |

## 2. Interfaces that change

**Python:** `deploys/preview.py` (new). `deploys/preview_views.py` (new). `deploys/urls.py`. `core/models.py` Site two fields + `0015_phase73.py`. `core/actions.py`. Frontend Sites.jsx. Acceptance NAMED. Append `conformance/demos/phase-7.md`.

**Not changed:** poller webhook absence. pipeline `execute`. overflow. Findings.jsx / Chrome.jsx / seed. No Beat job.

## 3. Applicable registry reqs

Task 0 — new MUST ids, phase 7, no `tier:`. `source: phase-7.3-design-note.md §3`. `--print-text-hashes`. Extend `PHASE_7_MUST_IDS` + `allowed_sources`. Subtract `P7-PREVIEW-DEMO`.

- `PREVIEW-PRIVATE-ONLY` — `phase: 7`, `verify: test`. `text:` create_preview refuses missing visibility and public repos and non-git parents; private visibility creates a mesh-only sibling Site with preview_of and preview_ref and does not call run_deploy.
- `PREVIEW-T2-HTTP` — `phase: 7`, `verify: test`. `text:` T2 POST site.preview_create Create preview type-the-parent-name; 201 returns site_id parent_id ref; 4xx public/missing visibility; tests inject visibility; no webhook route.
- `P7-PREVIEW-DEMO` — `phase: 7`, `verify: demo`, `demo: conformance/demos/phase-7.md`.

## 4. Exit demo

Git Project + Site, injected `visibility="private"`, T2 confirm parent name, ref `feature/pr-12` → 201, new Site mesh_only `preview-…-feature-pr-12`, `preview_of` set, no Deployment created. `visibility="public"` → 4xx `public repo refused`. Missing inject → 4xx. Record: append `conformance/demos/phase-7.md`. Honest: no live GitHub, no webhook, no auto-deploy, no U1, Pulumi/Azure parked.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-131** Protective cut — private-repo preview Site row + T2. No auto-deploy, no webhook, no live visibility API.
- **D-132** `0015_phase73.py`: `preview_of` FK + `preview_ref`. Exposure mesh_only. HTTP in `deploys/preview_views.py`.
- **D-133** Everyday gates stay phase 5 minus live. New ids phase 7 tier-less. U1 stays uncovered. Claim the two new deploys modules only.
- **D-134** Pulumi / managed-DB / LB upgrades stay later-if-it-grows (plan §7.2 / addendum §I). No product this phase.
- **D-135** Azure adapter stays demand-gated (review3 §V11). CloudProvider port + in-memory fake remain. No product this phase.

## 6. Protective cut (D-131)

MUST = private gate + sibling Site + T2 + park Pulumi/Azure. Auto-deploy / webhook / live GitHub / U1 are **OUT**.

## 7. Closed contract (binding)

**C1 Gate.** visibility ∈ {None, "public", "private"} only. public and None refuse. private creates one Site. Never `run_deploy`.

**C2 Schema.** Two columns only. `preview_of_id` null for ordinary sites. Name prefix `preview-`. No `\binstance\b` except existing tokens.

**C3 HTTP.** Label exactly `Create preview`. Serializer `{ref, confirm_name}`. generate-client. No `/webhook` / `/github` route added.

**C4 UI.** T2 ActionButton on site detail. NAV six.

**C5 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Do not mark demo ids.

**C6 Registry.** Task 0 adds the three ids + D-131…D-135. Do not rewrite 7.0–7.2 `text:`.

**C7 Module arrows.** `preview.py` may import Site/Project. No `scanner`, no `intake`. AST forbids webhook secret names.

**C8 Gate.** conformance-7 verifies the new ids; U1 uncovered-only allowed.
