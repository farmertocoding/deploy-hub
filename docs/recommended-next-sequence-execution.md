# Recommended Next Sequence — Detailed Execution Plan

**Prepared:** 2026-08-26  
**Operator update:** 2026-08-27  
**Repository baseline:** `master` at `02cfef1`  
**Document status:** Working execution plan; not a replacement for the frozen canonical plan copies in `docs/plan/`  
**Scope:** Restore a trustworthy green baseline, close the most valuable live operator gap, prove it on the test plane, and keep externally blocked work explicit.

## 1. Recommended outcome

The next development cycle should produce one complete, truthful operator path:

1. Every product and test-backed local gate is green; any external evidence dependency remains explicitly uncovered rather than fabricated.
2. The Sites screen shows only actions that belong to a Site.
3. Site adoption can be started and cancelled through an authenticated live API, not only through simulation or direct Python calls.
4. The adoption path is idempotent, asynchronous, observable, reversible before the production flip, and refuse-closed when its required seams or credentials are missing.
5. One real repository is adopted against an isolated test-plane target and the evidence records exactly what ran.
6. Other UI controls that lack a working live seam are either wired or visibly unavailable; none silently fail or imply capabilities the backend does not have.

Do not begin a new feature phase before this sequence is complete. The repository already has broad feature coverage; its highest-value next step is to make the existing operator surface internally consistent and genuinely executable.

### 1.1 Cloudflare operator status — 2026-08-27

The Cloudflare DNS-token and Origin CA-token human steps have been completed, with the following precise boundary:

- A least-privilege user API token was created for exactly one zone, `takko.market`, with `Zone DNS:Edit`.
- The token was pasted by the operator into **Deploy Hub → Settings → Cloudflare**. Deploy Hub verified it and stored it in the vault; the token value was not recorded in this document or read back from the vault.
- The resulting account has both a DNS token reference and an Origin CA token reference. It has no edge-token reference.
- Because the running Hub was in normal operator mode, the Settings endpoint initially created `takko.market` with `purpose=prod`. On 2026-08-27 the operator-approved local correction changed that row to `purpose=test`; a refusal check confirmed that normal production-mode provider construction now stops before credential loading. The row still is **not**, by itself, evidence that the T3 test runner is ready.
- `tests/test_t3_cf_live.py` does not consume the product Settings vault row. Its session fixture requires a separately supplied, process-local `HUB_TEST_CF_TOKEN`, observes that token, and creates its own `purpose=test` row in the test database.
- Do not export the product-vault secret to bridge these paths. At test execution time, the operator must inject the still-available token through an approved ephemeral secret channel, with `HUB_TEST_MODE=1` and `HUB_TEST_ZONE_SLUGS=takko.market` where applicable.
- Do not run a live DNS write merely to verify setup. The first mutation must be the credential-gated T3 DNS test after an explicit operator confirmation; it creates a uniquely named temporary record and removes it in `finally`.

Origin CA code has been migrated off the deprecated path. Cloudflare deprecated `X-Auth-User-Service-Key` authentication on 2026-03-19 and documents shutdown on 2026-09-30. `providers/cloudflare.py::origin_ca_request()` now sends `Authorization: Bearer` and refuses a `v1.0-` service key before any request. On 2026-08-27 the operator created a separate, exact-zone `takko.market` Bearer API token with `Zone → SSL and Certificates → Edit`, supplied it through a hidden local prompt, and Deploy Hub stored it under the account's `origin_ca_key_ref`. A redacted Cloudflare verification confirmed the token was active; the temporary plaintext and prompt helper were deleted, and the value was never printed or read back from the vault. Rebuilt web/worker runtime inspection confirmed the Bearer implementation is loaded, all seven Compose services are running, Redis persistence is healthy, and `manage.py check` reports no issues. The env name for a separately credentialed T3 process remains `HUB_TEST_ORIGIN_CA_KEY`; its value is the Bearer token, not a `v1.0-` service key. Focused verification passed 19 backend tests (with four credential/host-gated live skips), 9 frontend Cloudflare/checklist tests, Ruff, and the frontend production build. No Origin certificate has been issued; that live external mutation requires an explicit action-time operator confirmation and a defined cleanup/revocation path.

## 2. Why this order

The 2026-08-26 audit found the following baseline:

| Area | Observed state | Consequence |
|---|---|---|
| Python T1 suite | 2,392 passed, 6 skipped, 37 deselected, 1 failed in the restricted sandbox; that exact loopback-dependent test passed when rerun with permission | Product behavior is effectively green, but a clean full run still needs to be recorded in one suitable environment |
| Frontend tests | 234 passed, 1 failed | `target.router_probe` leaked into the Sites T3 action list |
| Python lint | One Ruff import-order error | `tests/test_overflow_destination.py` needs an import-only cleanup |
| Frontend production build | Passed | No build blocker |
| Django system check | Passed with development settings | No framework configuration blocker |
| Live adoption | Core flow and UI exist; `/api/v1/sites/{id}/adopt/` does not | The primary Phase 7 operator path returns 404 outside simulation |
| Preview creation | Route exists; view does not provide repository visibility | The live request always refuses with `visibility refused` |
| Router probe | Route exists; view intentionally passes `wan_probe=None` | The live action always refuses with `wan probe refused` |
| Site restart / check re-run | Buttons are rendered; no live execution engines were found | The UI overstates live capability |
| Named partner evidence | Intentionally absent | `PART-U1-NAMED-PARTNER` must remain uncovered until a real partner is named |
| Phase 7 conformance | Evaluates prior-phase requirements and therefore reports the missing named-partner demo as uncovered | Product work must not be blocked by—or falsely erase—this external dependency |

The first wave is deliberately small: restore signal before changing behavior. The adoption API is next because its domain logic, safety gates, UI, state presentation, cleanup owner, and tests already exist. Adding the missing transport/orchestration layer gives more value with less architectural invention than starting another feature.

## 3. Non-negotiable constraints

Apply these constraints to every work package below.

### 3.1 Evidence honesty

- Never convert a skipped live requirement into a fake pass.
- Never create `conformance/demos/named-partner.md` without a real partner supplied by the operator.
- Never invent `HUB_TEST_*`, Cloudflare, Tailscale, AWS, intake HMAC, webhook, or partner credentials.
- Record sandbox limitations separately from application failures. A test that only passes with loopback permission must be recorded as such.
- Do not claim a single clean full-suite run by combining separate runs. Run and record one complete session in an environment that supports the suite.

### 3.2 Test-plane containment

- Any live DNS, cloud, SSH, Docker, or router work must pass the existing test-plane wall.
- DNS work requires all existing keys: test mode, a `purpose=test` zone, and an allowlisted zone name.
- Use a disposable target and a test domain. Do not touch production DNS or production containers as part of this plan.
- Back up or snapshot state before the real-repository proof and define the cleanup command before starting it.

### 3.3 Architecture boundaries

- `deploys/` must not import concrete Cloudflare or cloud adapters. Resolve providers through their registries.
- Celery messages carry identifiers and harmless scalar options only. Secrets and environment bundle bytes must not enter broker payloads.
- Secrets are resolved inside the worker through the vault service.
- Provider absence is a refusal, not an implicit fallback to production SDK defaults or local credentials.
- Preserve the generated-client workflow: change serializers first, regenerate OpenAPI/types/action mirrors, then run the staleness gate.
- Do not hand-edit `frontend/src/api/action_tiers.js`, `frontend/src/api/openapi.yaml`, `frontend/src/api/types.ts`, or `frontend/src/api/zod.ts`.

### 3.4 Change discipline

- Preserve unrelated user files, including the currently untracked `.cursor/`, root `package-lock.json`, and `tmp/` paths.
- Keep recovery behavior reversible by default.
- Treat provider, vault, intake, authentication, deployment, and conformance-registry changes as sensitive-path changes requiring the repository's intended review.
- Add tests that fail for the old behavior before or with each behavior change.
- Do not weaken, narrow, deselect, waive, or reclassify a gate to make a change pass.

## 4. Execution overview

| Wave | Goal | Entry criterion | Exit criterion |
|---|---|---|---|
| 0 | Restore green signal | Current audited baseline | Frontend tests, Ruff, build, Django check, T1 tests, and generated checks are green; Phase 7 conformance has no failure except an explicitly external uncovered item |
| 1 | Make operator surfaces truthful | Wave 0 green | Every visible Site/Target action maps to the right resource and has an explicit live, unavailable, or simulated state |
| 2 | Implement the live adoption API | Wave 1 contract inventory complete | Authenticated start/cancel API dispatches the existing safe flow and reports state correctly |
| 3 | Prove adoption on a real repo in the test plane | Wave 2 green | One isolated TAKKO adoption and cleanup is recorded with evidence |
| 4 | Close or deliberately defer remaining live seams | Wave 3 evidence reviewed | Preview, router probe, restart, and re-run each work live or are honestly unavailable |
| 5 | Retire externally gated gaps | Operator supplies names/credentials/authorization | Named partner and credential-backed evidence are completed without fabricated artifacts |

Each wave is a merge boundary. Do not combine Wave 0 cleanup, the adoption API, and a live test-plane run in one review unit.

## 5. Wave 0 — Restore a trustworthy green baseline

### 5.1 Fix Site action scoping

**Problem**

`frontend/src/screens/Sites.jsx::t3SiteActions()` currently selects every globally defined T3 action. Adding `target.router_probe` to the shared action table therefore made a Target action render as a Site action and broke `frontend/tests/sites.test.ts`.

**Preferred implementation**

Make resource ownership explicit at the consumer boundary now, without changing the generated schema:

- Define the Site T3 identifiers as `site.rollback`, `site.restart`, and `check.rerun` in `frontend/src/screens/Sites.jsx`.
- Filter the generated `ACTION_TIERS` through that allowlist so labels, tiers, and undo windows still come from the canonical server table.
- Keep `target.router_probe` owned by `frontend/src/screens/Targets.jsx`.
- Do not infer resource scope from string prefixes alone because `check.rerun` is a Site-detail action without a `site.` prefix.

An action-table schema extension such as `resource: "site"` is a reasonable later cleanup only if multiple screens need the same ownership metadata. It is unnecessary for this one-line regression and would expand the generated API surface.

**Files expected to change**

- `frontend/src/screens/Sites.jsx`
- `frontend/tests/sites.test.ts` only if an additional negative assertion is needed

**Required tests**

- Assert exact equality with `['site.rollback', 'site.restart', 'check.rerun']`.
- Assert `target.router_probe` is absent from Site detail markup.
- Retain the Target-screen test proving the router action is still present there.

**Acceptance**

- The Sites screen contains no Target action.
- The Targets screen still contains `Probe router`.
- The shared action-tier labels and undo timing remain generated from `core/actions.py`.

### 5.2 Fix Ruff import order

**Problem**

Ruff reports one import-sorting error in `tests/test_overflow_destination.py`.

**Implementation**

- Apply Ruff's import ordering to that file only.
- Confirm the diff contains no behavioral changes.

**Acceptance**

- `ruff check .` exits zero.
- The test file's collected tests are unchanged.

### 5.3 Run the baseline gates

Run these from the repository root after the two fixes:

```bash
.venv/bin/ruff check .
make test-frontend
cd frontend && npm run build
cd ..
.venv/bin/python manage.py check --settings=hub.settings.dev
make check-generated
make test
make conformance-7
git diff --check
```

Environment notes:

- Run `make test` in an environment that permits the localhost redirect-defense test to bind loopback. Do not patch or skip that security test to accommodate a restricted sandbox.
- `make check-generated` may rewrite generated files before checking the diff. A clean result means those files remain unchanged.
- If the environment does not have the repository virtual environment activated, use the equivalent explicit interpreter consistently rather than mixing Python installations.
- `make conformance-7` must still be run and recorded. Until a real partner is supplied, `PART-U1-NAMED-PARTNER` is an accepted external blocker to overall conformance exit, not a product-green failure and not permission to waive or stub it. Every test-backed requirement and every requirement changed by the branch must pass.

**Stop condition**

Do not begin Wave 1 while any product or test-backed Wave 0 gate is red. Classify each failure as product, test, environment, stale generated output, or external evidence dependency and resolve it at the correct layer. The only permitted nonzero conformance condition at this boundary is a pre-existing, explicitly documented external requirement such as `PART-U1-NAMED-PARTNER`; new uncovered or failed requirements stop the sequence.

**Suggested commit boundary**

`fix(ui): scope T3 actions to their resource`

The import-only lint correction may be included in that small baseline-restoration commit if the diff remains obvious.

## 6. Wave 1 — Make the operator surface truthful

Wave 1 is a short contract audit followed by the smallest UI corrections. It prevents the adoption implementation from landing beside other misleading controls.

### 6.1 Build an action-to-engine inventory

For every action rendered by `Sites.jsx` and `Targets.jsx`, record:

| Field | Meaning |
|---|---|
| Action ID | Canonical identifier from `core/actions.py` |
| Owning resource | Site, Target, CheckRun, Partner, or another object |
| Tier | T1, T2, or T3 confirmation behavior |
| UI caller | Component and handler |
| HTTP contract | Method, route, request, success code, refusal codes |
| Execution engine | View/service/task/provider seam |
| Live readiness | Working, refuse-closed pending configuration, simulation-only, or missing |
| Evidence | Backend, frontend, acceptance, and live/test-plane proof |

Start with these known inconsistencies:

- `site.restart`: visible, but no live engine was found.
- `check.rerun`: visible, but no live engine was found.
- `site.preview_create`: live route exists, but visibility is never resolved.
- `target.router_probe`: live route exists, but the view always injects `wan_probe=None`.
- `site.adopt.start` and `site.adopt.cancel`: UI and simulation exist, but the route is absent.

### 6.2 Define visible states

Every operator control must be one of:

1. **Live:** the action calls a real authenticated endpoint and displays accepted, completed, refused, and failed outcomes.
2. **Unavailable with reason:** the button is disabled or replaced by text explaining the missing configured seam. It must not open a confirmation dialog that can only fail.
3. **Simulation-only:** shown only when simulation mode is explicitly active and labelled as simulation.

Do not hide an operational failure after a request has started. Refusals from a configured live engine should remain visible and link to their Finding or CheckRun where available.

### 6.3 Apply the minimum correction before adoption work

- Keep adoption controls visible because Wave 2 immediately supplies their live API.
- Mark restart and check re-run unavailable unless their engines are implemented in the same bounded change.
- For preview and router probe, show their current refuse-closed configuration state instead of implying success is possible.
- Preserve simulation fixtures, but ensure simulation responses cannot be confused with live responses.

**Acceptance**

- No action sends a request to a route known to be absent.
- No button appears actionable when its live dependency is unconfigured.
- Resource ownership is covered by frontend tests.
- Error copy distinguishes `not implemented`, `not configured`, `refused`, and `failed`.

## 7. Wave 2 — Implement the live Site adoption API

### 7.1 Close the contract in a focused design note

Before code, add a short design note under `docs/` that freezes the following contract. This avoids inventing lifecycle semantics inside a view.

**Recommended HTTP contract**

Preserve the client contract already present in `Sites.jsx`:

```text
POST /api/v1/sites/{site_id}/adopt/
```

Start request:

```json
{
  "live_compose_path": "/explicit/operator/path/docker-compose.yml"
}
```

Cancel request:

```json
{
  "cancel": true
}
```

`live_compose_path` is optional and must remain an explicit operator input. The server must not search `/srv/sites` or guess a path.

Recommended responses:

- `202 Accepted` for a newly queued start or cancel, returning CheckRun/task identity and current stage.
- `200 OK` for an idempotent repeat when the requested outcome already holds and no new work is queued.
- `400 Bad Request` for malformed input or invalid confirmation semantics.
- `401/403` for authentication/authorization failure.
- `404` for an unknown Site.
- `409 Conflict` for a lifecycle conflict such as start during cleanup, cancel after the production flip, or another active adoption holding the lock.
- `503 Service Unavailable` for an unconfigured required provider or transport seam when retry after configuration is valid.

If maintainers prefer separate REST routes for start and cancel, change the frontend and OpenAPI in the same contract commit. Do not support two undocumented contracts indefinitely.

### 7.2 Define lifecycle and cancellation semantics

The existing flow stages are `temp_dns`, `verify`, `flip`, `decommission`, and `cleanup`. The API design must define transitions rather than treating the worker as a black box.

Recommended state rules:

| Current state | Start | Cancel |
|---|---|---|
| No run / plan / abandoned | Queue adoption | Idempotent no-op |
| temp_dns | Return existing active run | Queue cleanup |
| verify | Return existing active run | Queue cleanup |
| flip | Do not pretend this is reversible; refuse automatic cancel and instruct rollback/recovery | Refuse with conflict |
| decommission | Return current run | Refuse with conflict |
| cleanup succeeded | Return completed run | Idempotent completed response |
| failed before flip | Allow an explicit retry after preserving failure evidence | Queue cleanup if temp resources may exist |

The UI currently names an `abandoned` presentation stage while the core cleanup owner writes `cleanup`. The design must choose one canonical persisted state and make the presentation mapping explicit. Do not add a second ambiguous terminal state to `CheckRun.results`.

### 7.3 Add the API layer

**Expected code surfaces**

- `deploys/adopt_views.py` for request/response serializers and the authenticated API view
- `deploys/urls.py` for the route
- `deploys/tasks.py` for start/cancel Celery entry points carrying IDs only
- A small orchestration service if desired assembly and locking do not belong in the view or task
- `tests/test_adopt_views.py` or the repository's closest existing adoption test module
- `frontend/src/api/*` generated outputs after serializer changes
- `frontend/src/screens/Sites.jsx` for real response handling and status refresh

**View responsibilities**

- Require authentication and the repository's normal authorization policy.
- Resolve the Site by ID.
- Validate `cancel` and `live_compose_path`; reject unknown fields if that matches existing serializer policy.
- Enforce allowed lifecycle transitions.
- Acquire or create the authoritative adoption CheckRun atomically.
- Queue a worker using only IDs and the validated path scalar.
- Return a serialized operation resource with no secret material.
- Never run SSH, Docker, DNS, or long probes inside the HTTP request.

**Worker/orchestration responsibilities**

- Reload the Site, target, zone, CheckRun, and vault-backed configuration from IDs.
- Assemble `desired` through the same production construction path used by the deployment system; do not duplicate the test fixtures' dictionaries in product code.
- Resolve DNS through `dns_provider_for(site.dns_zone)` and transport through the established target/transport construction seam.
- Call the existing `deploys.adopt_flow.adopt_flow()` for start.
- Call the existing single cleanup owner for an allowed cancellation.
- Persist success or failure state and a bounded, secret-scrubbed reason.
- File or resolve the existing orphan Finding when cleanup fails or later succeeds.
- Publish the repository's normal CheckRun/Finding update signal so the UI can refresh.

### 7.4 Concurrency and idempotency

Adoption changes traffic and must not rely on best-effort duplicate suppression.

- Use a database transaction and row lock around active-run selection/creation.
- Enforce at most one active adoption per Site at the service layer; add a database constraint only if it fits the existing CheckRun schema without unsafe JSON predicates.
- Repeated start requests return the same active run and do not create a second temp DNS name or container.
- Repeated cancel requests return the same cleanup operation.
- Worker retries resume from the persisted stage and reuse the existing temp name.
- A stale queued task must verify the CheckRun is still the active operation before mutating anything.
- Avoid holding a database transaction across SSH, Docker, HTTP, DNS, or health probes.

### 7.5 Failure and recovery behavior

Test each boundary independently:

- Missing primary target refuses before mutation.
- Missing DNS provider refuses for public adoption; mesh-only adoption deliberately has no DNS provider.
- Unmapped database/cache/volume dependencies refuse before flip.
- Health verification failure leaves the old stack serving and permits cleanup.
- Live compose drift refuses before flip.
- DNS upsert failure leaves the old production record/path intact.
- Old-container stop failure is recorded after the flip and produces an operator-visible recovery state; it must not be described as a successful clean adoption.
- Temp DNS cleanup failure files the existing P2 orphan Finding and remains retryable.
- Secret values, environment bundles, tokens, SSH material, and provider responses are scrubbed from task arguments, logs, CheckRun JSON, API responses, and Findings.

### 7.6 Backend test matrix

Add focused tests before the full gate run.

**HTTP and authorization**

- Anonymous start and cancel are rejected.
- Unknown Site returns 404.
- Invalid path type, overlong path, conflicting body fields, and unknown fields are rejected.
- Start returns 202 with operation identity and no secret fields.
- Cancel returns 202 only in cancellable stages.

**Lifecycle**

- First start creates/claims one active CheckRun and queues one task.
- Duplicate start returns the same operation and queues no duplicate.
- Cancel in `temp_dns` and `verify` queues cleanup.
- Cancel at/after `flip` refuses with 409.
- Duplicate cancel is idempotent.
- Retry after a pre-flip failure reuses the persisted temp identity.

**Seams and safety**

- Public adoption resolves an injected registry provider, not a concrete Cloudflare import.
- Mesh-only adoption does not request DNS.
- Missing provider/transport is refuse-closed.
- Celery calls contain IDs and the explicit path only.
- Broker args and serialized responses contain no known secret sentinel.
- Drift, health, mapping, volume, and cleanup failures preserve the core flow's safety behavior.
- Two concurrent starts result in one active operation.

**Regression**

- Existing direct `adopt_flow` tests remain unchanged and green.
- The temp reaper still calls the same cleanup owner.
- Import-boundary and sensitive-path tests remain green.

### 7.7 Frontend behavior

- On `202`, show the returned stage and operation identity, then refresh the Site payload through the existing data path.
- Disable start while an operation is active.
- Show cancel only during cancellable stages.
- Do not optimistically paint `flip`, `cleanup`, or success.
- Render 409 as a lifecycle conflict, 503 as missing configuration, and other failures as an error linked to the CheckRun/Finding when provided.
- Keep T2 confirmation copy explicit about the production flip, old-path decommission, and registered volumes.
- The undo affordance must call the defined cancel operation only while cancellation is safe. After flip, direct the operator to rollback/recovery instead.

### 7.8 Generated artifacts and gates

After serializers and URLs are stable:

```bash
make generate-client
make check-generated
make test-frontend
cd frontend && npm run build
cd ..
make test
make conformance-7
git diff --check
```

Inspect the OpenAPI diff. Confirm the adoption route, request union/fields, response codes, and response schema match the design note. Generated output is part of the implementation commit.

### 7.9 Wave 2 definition of done

- Live mode no longer returns 404 for Site adoption.
- Start and cancel are authenticated, authorized, documented, and generated into the client schema.
- Long-running work is outside the request process.
- Duplicate requests and worker retries are safe.
- Cancellation is allowed only before the production flip.
- Missing seams refuse without mutation.
- The UI shows the server's real state rather than a simulated stage.
- Focused tests, full T1, frontend tests, build, and generated checks pass; Phase 7 conformance introduces no failure or uncovered item beyond the documented external named-partner dependency.

**Suggested commit sequence**

1. `docs(adopt): freeze live API and lifecycle contract`
2. `test(adopt): specify HTTP lifecycle and idempotency`
3. `feat(adopt): add asynchronous live start and cancel API`
4. `feat(ui): bind Site adoption to live operation state`
5. `chore(api): regenerate adoption client contracts`

These can be reviewed as one branch but should remain separable commits.

## 8. Wave 3 — Real-repository test-plane adoption proof

### 8.1 Recommended specimen

Use **TAKKO** first.

Reasons:

- It is one of the two declared real-repository demos.
- Earlier project records describe it as the first repository proven end to end in the pre-product spike.
- Its Django + Vite shape exercises a representative multi-service adoption.
- The Phase 2 TAKKO real-pipeline half remains explicitly outstanding, so this run can close a real evidence gap without inventing a new specimen.

Use `SATURDAYS_site` instead only if the purpose of the run is specifically to exercise its scheduler/heartbeat characteristics. Do not expand the declared demo set casually.

### 8.2 Entry checklist

- Wave 2 is merged or on a clean candidate branch with all T1/frontend gates green.
- The TAKKO tree and exact revision are recorded.
- Scanner blockers are understood and an approved `deployhub.yaml` exists; do not bypass scanner findings.
- A disposable enrolled Target has `purpose=test` and sufficient resources.
- A disposable test DNS zone is allowlisted under the existing test-plane controls, or the run is deliberately mesh-only.
- If public DNS is exercised, the test runner receives the single-zone token through an approved ephemeral `HUB_TEST_CF_TOKEN` channel. The product Settings vault row does not satisfy this fixture precondition.
- The run sets `HUB_TEST_MODE=1`; `takko.market` is present in `HUB_TEST_ZONE_SLUGS`; and the fixture-created `DnsZone` is `purpose=test`.
- The operator has explicitly approved the first live DNS mutation after reviewing that the test creates only a uniquely named temporary record and deletes it in fixture cleanup.
- The product account now has a vaulted Bearer token with `SSL and Certificates:Edit`, but T3 still requires its own approved ephemeral `HUB_TEST_ORIGIN_CA_KEY` injection. Do not export or read back the product-vault secret, and do not use a `v1.0-` service key.
- The old stack, its volumes, and its current production/test-plane DNS are inventoried.
- A backup/snapshot has been created and its restore procedure tested or already evidenced.
- The expected health endpoint, warmup time, database/cache mappings, named volumes, and old container name are recorded.
- Cleanup commands and the responsible operator are written down before start.

If any credential or containment item is missing, stop. Do not substitute a personal default SDK chain or a production zone.

### 8.3 Dry run

1. Scan the exact TAKKO revision and archive the report.
2. Confirm service classification and all database/cache/volume mappings.
3. Confirm the target and DNS zone satisfy the test-plane wall.
4. Exercise the API with a deliberately missing seam and verify it refuses without a CheckRun mutation beyond the refusal record.
5. In simulation mode, verify the confirmation copy and request body.
6. Confirm the real UI is not using the simulation adapter.

### 8.4 Live test-plane run

1. Start the old TAKKO stack on the isolated target and verify the old test URL.
2. Capture baseline container, volume, DNS, and health state.
3. Start adoption through the Sites UI, not through a direct Python call.
4. Confirm the API returns 202 and one active CheckRun.
5. Confirm exactly one temp container and, for public test mode, one temp DNS record are created.
6. Verify the old URL continues serving during `temp_dns` and `verify`.
7. Confirm the temp health probe validates the intended image tag.
8. Allow the test-plane production-name flip.
9. Confirm the production test name serves the adopted stack.
10. Confirm the old container is decommissioned only after successful verification and flip.
11. Confirm registered volumes still exist and application data is intact.
12. Confirm temp DNS and temporary container state are removed by the single cleanup owner.
13. Confirm the CheckRun reaches successful cleanup and no orphan Finding remains open.
14. Run the duplicate-start request after completion and prove it does not create another temp identity.

### 8.5 Cancellation drill

Run a second isolated adoption only if the first run's cleanup is verified:

1. Start adoption and pause/inject a controlled pre-flip verification failure.
2. Cancel through the Sites UI while at `temp_dns` or `verify`.
3. Confirm the old URL continues serving.
4. Confirm temporary DNS/container resources are removed.
5. Confirm registered volumes and the old stack are untouched.
6. Repeat cancel and confirm idempotency.

Do not test cancellation after flip as a destructive experiment. The API test suite should prove the refusal; live recovery after flip belongs to the existing rollback path.

### 8.6 Evidence to capture

Create a dated evidence record under the established conformance demo location only after the run occurs. Include:

- repository name and exact revision;
- Hub revision;
- target identity with secrets removed;
- test-plane zone identity;
- start/cancel request timestamps and status codes;
- CheckRun ID and stage sequence;
- pre/post health results;
- redacted DNS record transitions;
- container/volume state before and after;
- cleanup result;
- gate results;
- any skipped step and the exact reason;
- rollback or restoration performed.

Do not paste tokens, environment files, SSH material, database URLs, cookies, or unredacted provider responses.

### 8.7 Rollback boundary

Before flip, cancellation owns rollback: stop the temp container, delete only the temp DNS record, keep the old path serving, and retain registered volumes.

After flip, use the explicit Site rollback/recovery procedure. Do not relabel post-flip recovery as adoption cancellation. If old-path decommission or cleanup fails, preserve the CheckRun and Finding evidence until recovery is complete.

### 8.8 Wave 3 definition of done

- A real TAKKO revision passed through the live UI and API against isolated infrastructure.
- The old path remained available until verification succeeded.
- DNS/container/volume transitions matched the contract.
- Pre-flip cancel and duplicate requests were proven safe.
- All temporary resources were removed or an honest open Finding identifies what remains.
- Evidence is reproducible, redacted, and tied to exact revisions.

## 9. Wave 4 — Close remaining live seams or remove the promise

Do these as separate, value-ranked vertical slices after adoption proof.

### 9.1 Preview repository visibility

**Current issue:** `SitePreviewCreateView` calls `create_preview(parent, ref)` without `visibility`, and the service correctly refuses `None`. Live preview creation therefore always returns `visibility refused`.

**Recommended next slice:** add a repository metadata seam that resolves visibility from the configured Git provider.

- Resolve visibility server-side from the Project's authenticated repository integration.
- Never trust a client-supplied `visibility: private` claim.
- Refuse public, unknown, unavailable, and mismatched repositories.
- Keep the current behavior that creates only a mesh-only sibling Site and does not silently deploy it.
- Add fake-provider T1 tests and an optional test-plane integration behind existing credential walls.
- If no provider integration is configured, render preview creation as unavailable with that reason.

### 9.2 Router WAN probe

**Current issue:** `RouterProbeView` intentionally calls `probe_nothing_forwarded(target, wan_probe=None)`, so its live POST always refuses.

**Recommended next slice:** define an allowlisted, read-only WAN-probe adapter selected from Target/zone configuration.

- Do not accept probe results or a probe-enable flag from the request body.
- Resolve a server-side adapter with bounded timeout and output validation.
- Keep `None` refuse-closed.
- File Findings only from a successful trusted probe, never from missing configuration.
- Show unavailable in the UI when no probe adapter is configured.
- Prove Target resource ownership so this action cannot leak back onto Sites.

### 9.3 Site restart and check re-run

Choose one of two honest outcomes for each action:

- Implement an authenticated endpoint, idempotent service/task, audit record, real status response, and tests; or
- Remove/disable the action on live screens until that complete path exists.

Do not implement a UI-only handler, a 202 response without a worker, or a worker that guesses which container/check to operate on.

Recommended priority:

1. `check.rerun`, because an explicit CheckRun ID can make the target unambiguous and the action is diagnostically useful.
2. `site.restart`, only after restart semantics identify the exact SiteInstance/container and define health verification plus failure recovery.

### 9.4 Wave 4 definition of done

For each of the four surfaces—preview, router probe, check re-run, and restart—one statement is true and tested:

- it works through a real configured live seam; or
- it is visibly unavailable and sends no doomed request.

Simulation-only behavior remains clearly labelled and cannot satisfy live evidence.

## 10. Wave 5 — User- and credential-gated exits

These items must not block Waves 0–4, and Codex must not fabricate the missing inputs.

### 10.1 Named partner

**Blocked on:** the operator naming and authorizing a real partner.

After that input exists:

1. Confirm what data may be recorded publicly in the repository.
2. Exercise the existing partner intake, signature verification, replay/idempotency, isolation, webhook, kill switch, and test-zone template path.
3. Redact partner secrets and sensitive identifiers.
4. Create `conformance/demos/named-partner.md` only from the completed run.
5. Run `conformance-5.5` and confirm `PART-U1-NAMED-PARTNER` becomes verified by its declared demo mechanism.

Until then, keep it uncovered. Do not add a waiver or a fixture masquerading as the named partner.

### 10.2 Credential-backed live evidence

**Blocked on:** approved test-plane credentials and operator authorization.

Potential evidence includes:

- Cloudflare test-zone behavior;
- Let's Encrypt staging behavior;
- Tailscale/test mesh behavior;
- live AWS or other cloud test-account behavior;
- real Git provider visibility for previews;
- real WAN router probe integration.

For each integration, verify the existing test-plane wall before execution, use least-privilege credentials, define a spend/time cap, and record cleanup. Missing credentials remain an honest skip.

### 10.3 Governance/process waivers

After product paths are green, review active process and mutation-equivalent waivers one at a time.

- Retire a waiver only when its underlying control is implemented and independently tested.
- Do not replace a waiver with a weaker echo/placeholder gate.
- Finish the sensitive-path guard before declaring branch protection/process coverage complete.
- Keep mutation scope and conformance registry anti-gaming tests intact.

## 11. Cross-wave verification matrix

| Change type | Focused verification | Required broad verification |
|---|---|---|
| Frontend action scoping | `frontend/tests/sites.test.ts`, Target tests | `make test-frontend`, frontend build |
| Python import-only cleanup | Ruff on changed file | `ruff check .` |
| Serializer or API route | View tests, schema assertions | `make generate-client`, `make check-generated`, T1, frontend tests/build |
| Celery orchestration | IDs-only args, retry/idempotency tests | T1, import-boundary tests, Phase 7 conformance |
| Provider/transport resolution | Fake seam, missing-seam refusal | T1 plus credential-gated test-plane test where available |
| DNS/container mutation | Failure injection and cleanup tests | Test-plane proof; never production as routine verification |
| Conformance registry/demo | Exact requirement test or completed evidence | Appropriate `conformance-*` target without tier falsification |
| Documentation only | Link/path review, `git diff --check` | No product suite required unless the document changes a gate contract |

## 12. Risk register

| Risk | Prevention | Recovery |
|---|---|---|
| Duplicate adoption flips or temp resources | Row lock, one active operation, idempotency key/run reuse | Reaper plus single cleanup owner; preserve Finding evidence |
| Cancellation after traffic flip loses service | Make post-flip cancel a conflict | Use explicit rollback/recovery path |
| Secret leakage through Celery/API/logs | IDs-only tasks, vault resolution in worker, sentinel tests | Revoke exposed credential, scrub artifact, file incident; do not merely redact the test |
| Test-plane request reaches production | Existing triple-key walls and explicit target/zone checks | Abort before mutation; if a mutation occurred, execute provider-specific rollback and incident review |
| UI reports simulated success as live | Separate adapters/state labels and server-returned operation state | Remove optimistic state; refresh authoritative Site/CheckRun data |
| Preview trusts client visibility | Server-side provider metadata only | Refuse unknown; delete unintended preview Site if one was created |
| Router request forges probe results | Never bind probe data from request | Discard result, resolve false Finding, audit the path |
| Full suite appears red only in sandbox | Run one complete session with loopback support | Record environment limitation without weakening the security test |
| Generated client drifts | Regenerate and run staleness gate in API commit | Regenerate from serializers; never patch generated files manually |

## 13. Branch and review sequence

Use small branches with the Codex branch prefix when branches are created:

1. `codex/restore-green-baseline`
2. `codex/truthful-operator-actions`
3. `codex/live-site-adoption-api`
4. `codex/takko-adoption-test-plane`
5. One branch per remaining live seam

Rebase/merge each only after its own exit criteria pass. The test-plane evidence branch should contain evidence and narrowly required fixes, not unrelated feature work.

## 14. Explicit non-goals for this sequence

- Starting an undefined Phase 8.
- Adding Azure, Pulumi, auto-scaling policy, or other parked roadmap work.
- Turning simulation fixtures into claimed live evidence.
- Adding production credentials to development or CI.
- Using default cloud SDK credential chains.
- Creating a named-partner artifact from a test fixture.
- Weakening current import, registry, mutation, authentication, sensitive-path, or conformance gates.
- Refactoring working modules solely for style while the live operator gaps remain.

## 15. Immediate execution checklist

The first work session should do exactly this:

- [x] Add a negative frontend test that Site actions exclude `target.router_probe`.
- [x] Scope `t3SiteActions()` to the three Site-detail T3 actions.
- [x] Apply the Ruff import-only fix.
- [x] Run all Wave 0 gates in the correct environment and save the results.
- [x] Create the action-to-engine inventory from Wave 1.
- [x] Make restart, check re-run, preview, and router probe truthfully reflect live readiness.
- [x] Write and review the adoption API/lifecycle design note.
- [x] Add failing adoption HTTP, lifecycle, concurrency, and secret-boundary tests.
- [x] Implement the authenticated asynchronous start/cancel API.
- [x] Bind Sites UI state to the real operation response.
- [x] Regenerate and verify API client artifacts.
- [x] Run the complete Wave 2 gate set.
- [ ] Prepare the TAKKO test-plane entry checklist and obtain only the required authorization/credentials.
- [x] Create and vault-connect a least-privilege, single-zone DNS token for `takko.market`, correct the local row to `purpose=test`, and verify normal production mode refuses provider construction; do not treat the product vault row alone as T3 readiness.
- [x] Migrate Origin CA authentication to Cloudflare's Bearer-token flow, refuse legacy service keys, update the Settings/registry vocabulary, and pass focused backend/frontend/static/build verification before collecting that credential.
- [x] Create, verify, and vault the separate exact-zone Origin CA Bearer token for `takko.market`; delete temporary plaintext, rebuild/restart the runtime, and leave certificate issuance unperformed pending explicit confirmation.
- [ ] Inject the DNS token ephemerally for the T3 process and verify the triple-key wall without printing or persisting the token.
- [ ] Obtain explicit operator confirmation immediately before the first temporary DNS upsert/delete test.
- [ ] Run and record the live adoption and pre-flip cancellation drill.
- [ ] Review the result before selecting the next live seam from Wave 4.

## 16. Final definition of done

This recommended sequence is complete when:

- the repository has a reproducible green baseline;
- resource actions do not leak between screens;
- visible controls tell the truth about live readiness;
- adoption start and safe pre-flip cancellation work through the authenticated UI/API;
- the operation is idempotent, retryable, observable, and secret-safe;
- TAKKO has completed one isolated test-plane adoption with reproducible redacted evidence;
- temporary resources are cleaned or represented by an unresolved Finding;
- all relevant frontend, T1, generated, and build gates pass, and Phase 7 conformance has no branch-caused failure or uncovered requirement;
- remaining named-partner and credential-backed requirements are explicitly waiting on real operator inputs, with no stub or invented evidence.
