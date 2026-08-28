# Deploy Hub zero-trust audit

**Date:** 2026-08-28 (Asia/Taipei)  
**Audited state:** branch `codex/origin-ca-bearer-token`, HEAD `907305e1f491`, including the dirty working tree and untracked files present during the audit  
**Decision:** **FAIL — do not deploy or merge as a zero-trust-ready release**

## Executive summary

The current tree has strong security primitives, but it does not meet a zero-trust release bar. The most serious defect grants a 2FA-enrolled, session-verified user with no persisted workspace membership the full owner mutation capability set in the default workspace. Other release blockers include cross-workspace findings and audit attribution, viewer-authorized finding suppression, tenant roles controlling global resources, a user-controlled worker path crossing into scanners/build contexts, shared worker credentials and KEK access, and the absence of production off-host audit shipping.

The mechanical release evidence is also red. T1 produced 2,490 passes and one deterministic gate failure. The all-tier run produced 2,504 passes, one failure, and 16 T3 errors because Multipass could not connect to its socket. The mutation gate could not establish a clean baseline and left all 908 mutants unchecked. Generated API artifacts are stale. Phase 7 and phase 3 all-tier conformance fail. Supplemental JavaScript audits found 5 frontend and 18 sample-workspace advisories.

## Scope and method

Three expert tracks were used:

1. Zero-trust architecture: authentication, authorization, tenancy, WebSocket/worker boundaries, auditability, and fail-open behavior.
2. Product and supply-chain security: secrets, crypto, SSRF/injection/path handling, dependencies, containers, and deployment configuration. This expert track hit its execution limit after returning its high-confidence findings; the primary audit independently traced those findings and completed the tooling review.
3. Test and mutation quality: canonical gate discovery, gate integrity, mutation scope, frontend coverage, and live-tier limitations.

The audit was read-only except for this report and normal gate-generated/ignored artifacts. The generated-client check was run in an isolated mirror of the current dirty tree to avoid overwriting the user's API files. No live cloud credentials were invented or used.

## Gate scoreboard

| Gate / check | Result | Evidence |
|---|---:|---|
| `make lint` | PASS | Ruff passed; Bandit returned no findings; `pip-audit -r requirements.txt` found no known vulnerabilities. The first sandboxed audit could not bootstrap; the authorized rerun passed. |
| `make log-scrub` | PASS | No prohibited `SECRET_KEY =` assignment in the configured Python package roots. |
| `make scripts-lint` | PASS | ShellCheck, `shfmt -d`, and `bash -n` passed for all five host scripts. |
| `python -m pip check` | PASS | No broken Python requirements. |
| Django dev system check | PASS | No issues. |
| Django production deploy check | WARN | Boot fail-closed behavior worked. With an audit-only 0400 key and valid HTTPS public URL, the check completed with 25 warnings: OpenAPI operation collisions/missing serializer metadata and optional HSTS subdomain/preload settings. |
| `make test` | **FAIL** | 2,490 passed, 6 skipped, 37 live tests deselected, 1 failed in 649.48 s. Failure: `tests/test_mutation_gate.py::test_the_cache_watches_every_file_the_sandbox_can_read`; runtime `sample-node-site/data/app.sqlite3-shm` was enumerated but excluded from the derived watch set because it is ignored. |
| `make test-all` | **FAIL** | 2,504 passed, 13 skipped, 1 failed, 16 errors in 900.21 s. The same cache-watch failure recurred. All 16 errors were T3 fixture failures caused by `multipass ... cannot connect to the multipass socket`; T2's 14 additional tests passed. |
| Frontend `npm run quality` | PASS | ESLint passed with zero warnings; 286/286 unit tests passed; Vite production build passed. |
| Frontend `npm run test:e2e` | PASS | 13/13 Chromium tests passed: dark/light WCAG 2.1 AA checks, visual baselines, and compact navigation. |
| `make mutation` | **FAIL** | Clean baseline errored on an invalid `core_dnsaccount.workspace_id` foreign key during phase-1 acceptance teardown. All 908 mutants remained `not checked`; the fail-closed wrapper rejected the run. Nine declared waivers were present but did not convert unchecked outcomes into passes. |
| `make check-generated` | **FAIL** | Isolated regeneration changed `frontend/src/api/openapi.yaml`, `types.ts`, and `zod.ts`; the committed/current artifacts are stale relative to serializers. |
| `make conformance` (phase 5, non-live) | PASS | 184 requirements: 172 verified, 6 skipped-only, 6 uncovered; eight source-anchor warnings. |
| `make conformance-7` | **FAIL** | Missing `conformance/demos/named-partner.md` for `PART-U1-NAMED-PARTNER`. |
| `make conformance-3` after all-tier run | **FAIL** | Eight requirement groups failed because their T3 tests errored when Multipass was unavailable. |
| Frontend `npm audit` (supplemental) | **FAIL** | 5 advisories: 4 high, 1 moderate. Affected resolved packages include `js-yaml@4.3.0`, `nanoid@3.3.17`, and `vite@5.4.21`/`esbuild@0.21.5`. |
| Sample workspace `pnpm audit` (supplemental) | **FAIL** | 18 advisories: 5 high, 10 moderate, 3 low. Runtime packages include `fastify@5.2.1` and `ws@8.18.0`; dev Vite is `6.0.11`. |
| Composite `review-round` / `nightly-gates` | **FAIL (derived)** | Their required component gates above are red. Re-running the wrappers would not change the component evidence and would repeat the 11–15 minute suites. |

Environment note: local Python was 3.13.14/Django 5.2.17, while CI declares Python 3.12. The npm wrapper exposed Node 26.5.0 and the pnpm wrapper reported Node 24.19.0, while the sample workspace requires Node 22. This is a reproducibility limitation.

## Findings

### ZT-01 — Critical — Users without membership receive owner mutation authority

**Evidence:** `core/rbac.py:124-131` creates an implicit default-workspace membership for any authenticated user with no memberships and labels it `deployer`. `core/rbac.py:212-224` then authorizes that implicit user against `ROLE_CAPABILITIES["owner"]`, which includes `secrets.manage`, `members.manage`, and `lifecycle.destroy` at `core/rbac.py:33-38`. Read endpoints using `RequireWorkspace` also accept the implicit membership. `tests/test_webauthn_t1.py:243-278` proves reachability by creating a normal membership-free user and successfully deleting a target after touch.

**Impact:** A 2FA-enrolled, session-verified account that was never granted a tenant role can read default-workspace resources and perform configuration, deployment, secret, and destructive lifecycle actions. HUD membership actions separately require displayed `admin_read`, which this implicit non-staff identity lacks.

**Remediation:** Remove implicit non-staff membership. Bootstrap exactly one explicitly identified initial owner in a one-time transaction. Require a persisted membership for every read and mutation. Add zero-membership 403 tests for representative read, T2, and T1 endpoints.

### ZT-02 — High — User-controlled local paths cross the host/worker boundary

**Evidence:** `wizard/views.py:364-415` accepts any non-empty `local_path` with no canonical-root or ownership validation; project creation requires only `config.write` (`core/rbac.py:66-69`, `wizard/views.py:434-466`). `wizard/hud_workers.py:7-21` scans that host path asynchronously. Adopt desired state copies it into `source_dir` (`deploys/adopt_service.py:146-177`), and `deploys/steps.py:43-62,1154-1173` recursively reads and uploads the directory as a remote Docker build context, excluding only symlinks, Dockerfile, environment filenames, and two exact marker values.

**Impact:** A deployer can point the Hub at directories readable in the executing worker's filesystem, disclose filenames/content through scanning, and—through the adopt/build path—copy that data to a deployment target. In Compose this includes mounted data such as `/etc/deploy-hub/vault.key`; broader host data is exposed only if mounted into the worker or when running workers directly on the host. The implicit-authority defect in ZT-01 makes this reachable by an unassigned account.

**Remediation:** Disable API-created `local_path` projects in production or confine them to an operator-configured source root using `resolve()` plus descendant checks, ownership/mode validation, a deny-by-default file policy, size limits, and a dedicated low-privilege scanner/build identity. Never archive an API-selected host path directly.

### ZT-03 — High — Findings are globally keyed and default-workspace attributed

**Evidence:** `core/models/fleet.py:831-846` gives `Finding.workspace` a default workspace and keeps `fingerprint` globally unique. `core/findings.py:73-103` globally looks up/upserts by fingerprint and usually creates without a workspace. Producers such as `monitor/alerts.py:64-82` omit workspace. The API then filters by workspace (`monitor/views.py:71-92`).

**Impact:** Non-default tenants can lose their alerts, default-workspace users can receive another tenant's resource details, and identical tenant fingerprints collide into one row.

**Remediation:** Require a workspace or workspace-owning object on every filing. Make uniqueness `(workspace, fingerprint)` and scope every lookup, transition, stale-resolution, and alert-state query. Migrate existing rows from referenced resources where possible.

### ZT-04 — High — Audit events are assigned to the wrong tenant

**Evidence:** `core/audit.py:30-47` defaults every call that omits `workspace` to the default workspace instead of deriving it from `obj` or request context. Many tenant actions pass an object but no workspace. The audit UI filters by selected workspace in `core/hud/collections.py:241-280`.

**Impact:** Tenant actions disappear from the correct audit trail and may be exposed to default-workspace auditors, undermining investigations and non-repudiation.

**Remediation:** Make workspace mandatory or deterministically inferred. Reject ambiguous events rather than defaulting. Add multi-workspace attribution tests for every privileged action family.

### ZT-05 — High — Viewer can suppress active security findings

**Evidence:** Viewers receive `admin_read` (`core/rbac.py:16-18`), but `finding.ack` and `finding.transition` map to that read capability (`core/rbac.py:81-82`). `monitor/views.py:95-123` allows ack, resolve, and accept-risk. Accepted findings remain quiet on the same fingerprint (`core/findings.py:11-14`).

**Impact:** A read-only tenant member can conceal incidents and suppress recurring alerts.

**Remediation:** Add `findings.manage`, grant it only to appropriate operator/admin roles, and reserve accept-risk for a stronger role with optional recent-touch enforcement.

### ZT-06 — High — Tenant roles authorize platform-global changes

**Evidence:** `core/partner_views.py:450-487` checks workspace-scoped `lifecycle.destroy` and then changes the global singleton `PartnerApiFlag` (`core/models/fleet.py:418-438`). `core/aws_views.py:56-63,95-150` checks workspace-scoped `secrets.manage` but overwrites the global `HUB_AWS_CREDENTIALS_REF` secret.

**Impact:** An owner of any tenant can toggle partner intake for every tenant; an admin or owner of any tenant can replace the global AWS credentials.

**Remediation:** Introduce a separate system-administrator plane for global resources or make these resources workspace-owned. Never authorize a global mutation using an arbitrary tenant role.

### ZT-07 — High — Queue labels do not provide worker isolation

**Evidence:** `docker-compose.yml:22-75` reuses the same DB/Redis credentials for web, all workers, and Beat. Deploy, probe, control, and Beat all mount the same vault-key volume. `hub/settings/base.py:225-253` uses the same Redis credential for Channels and Celery; queues are logical routes only.

**Impact:** Compromise of a lower-trust probe worker yields the KEK, broad database access, and the ability to publish privileged control/deploy tasks.

**Remediation:** Split DB roles, Redis ACL users/passwords, worker identities, networks, and mounts. Give KEK access only to processes that decrypt. Authenticate task envelopes and reauthorize workspace/resource identity in the executing worker.

### ZT-08 — High — Production off-host audit protection is absent

**Evidence:** `core/audit_ship.py:1-5` states that the shipper is an in-process fake and the live Object Lock adapter is absent. `core/audit_ship.py:41-48` fails with no injected store. Although `HUB_AUDIT_S3_BUCKET` exists, no production task or schedule calls `ship()`.

**Impact:** A database compromise can rewrite or erase the only in-repository durable audit trail. An externally configured log collector was outside the inspected code and remains unverified.

**Remediation:** Implement an append-only/Object-Lock provider, schedule incremental shipping, alert on unshipped age, and verify/restorable chains independently of the Hub database.

### ZT-09 — Conditional High — Sample workload runtime dependencies have known vulnerabilities

**Evidence:** Supplemental `pnpm audit` found `fastify@5.2.1` affected by content-type validation bypass and forwarded-host/protocol issues, and `ws@8.18.0` affected by memory exhaustion and memory disclosure. The frontend audit also found high advisories, although its affected graph is primarily build/development tooling.

**Impact:** If the sample Node service is shipped or used as a real deployed workload, crafted requests or WebSocket frames may bypass validation, exhaust memory, or disclose uninitialized memory. If it remains a non-production fixture, this is Medium supply-chain/test-fixture risk rather than a control-plane runtime vulnerability.

**Remediation:** Upgrade Fastify to a version satisfying all fixes (at least 5.8.3 at audit time), `ws` to at least 8.21.0, and Vite/build dependencies to supported patched versions; regenerate lockfiles under Node 22 and add npm/pnpm audits to CI.

### QG-01 — High — Parallel Make can invalidate gate ordering

**Evidence:** The Makefile rejects several false-green flags but not `-j`/`--jobs` (`Makefile:41-47`). `review-round` lists test, mutation, and conformance as sibling prerequisites (`Makefile:256-264`) and has no `.NOTPARALLEL`. The ordering test explicitly guarantees only a serial build (`tests/test_mutation_gate.py:152-161`).

**Impact:** `make -j review-round` can start mutation before a green baseline and conformance before pytest writes the current run report, producing invalid or stale evidence.

**Remediation:** Reject jobserver/parallel flags fail-closed, declare the sensitive aggregate `.NOTPARALLEL`, or encode true dependency edges.

### QG-02 — High — Mutation evidence is both broken and too narrow for zero trust

**Evidence:** The run left 908/908 mutants unchecked because the clean baseline violated a workspace foreign key. Scope covers only five files in `pyproject.toml`; critical RBAC, permission, vault, worker, tenant-isolation, and task-dispatch code is not mutated. The protected floor in `tests/test_mutation_gate.py:40` still names only the original three modules, so newer `scanner/presentation.py` and `hub/renderers.py` can be removed without the advertised direct anti-narrowing assertion firing.

**Impact:** No mutation-strength claim is currently valid, and even a passing configured gate would not demonstrate resistance in the most important zero-trust boundaries.

**Remediation:** Fix the workspace fixture/FK baseline first, update the protected floor, expand mutation in risk-based batches to authorization and tenancy seams, and pin/hash the resolved test environment used for cached verdicts.

### ZT-10 — Medium — Audit chain can fork and omits security context

**Evidence:** `core/audit.py:23-27` reads the last row without serialization, allowing concurrent writers to share a predecessor. `core/audit.py:8-20` omits workspace and partner IDs from the canonical hash payload. `core/models/fleet.py:57-60` cascades audit deletion with workspace deletion.

**Remediation:** Serialize append with a chain-head lock, hash every security-context field, continuously verify the chain, and retain audit rows independently of workspace lifecycle.

### ZT-11 — Medium — Intake permits plaintext, unauthenticated, unbounded traffic

**Evidence:** `monitor/intake_poll.py:68-106` sends no service authentication and reads the full response without a byte cap. `monitor/intake_poll.py:109-123` accepts HTTP. Git-push items bypass partner signature verification at `monitor/intake_poll.py:284-305`.

**Impact:** A malicious/intercepted endpoint can expose metadata, exhaust worker memory, suppress or acknowledge work, and influence deployment timing. Code injection is constrained because the Hub re-resolves repository head rather than trusting the supplied SHA.

**Remediation:** Require production HTTPS plus mTLS or pinned service authentication, strict host allowlisting, bounded bodies, authenticated acknowledgements, and authenticated envelopes for every item type.

### ZT-12 — Medium — Authentication abuse and denials lack controls/evidence

**Evidence:** `hub/settings/base.py:127-144` declares no DRF throttles; `core/views.py:32-80` has no login limiter/lockout. `core/exception_handlers.py:96-120` audits serializer validation errors but not authentication/permission denials. Login uses `REMOTE_ADDR` directly rather than the trusted-hop-aware client IP helper.

**Remediation:** Add bounded per-IP and per-account authentication throttles, centralized authentication/authorization-denial audit, generic responses, and trusted-hop client-IP attribution.

### QG-03 — Medium — Release gates omit frontend and browser checks

`review-round` runs frontend unit tests but not the package's ESLint/build quality command. Push CI builds but does not run ESLint. Neither CI nor `review-round` runs the Playwright accessibility/visual suite that passed during this audit.

**Remediation:** Make `npm run quality` and the stable Playwright accessibility suite mandatory, with visual checks either gated or explicitly reviewed.

### QG-04 — Medium — Secret and dependency scanning coverage is incomplete

The built-in dependency gate audits only production Python requirements. It does not audit development Python dependencies or either JavaScript lockfile. `log-scrub` is a narrow `SECRET_KEY =` grep and explicitly excludes tests, conformance, and developer scripts.

**Remediation:** Add repository-wide secret scanning, audit every lockfile/ecosystem, and document justified exclusions. Keep fixtures safe through allowlisted fake-secret patterns rather than directory-wide omissions.

### QG-05 — Medium — Generated API contracts are stale and schema generation warns

The isolated `check-generated` run changed OpenAPI, TypeScript, and Zod output. Production `check --deploy` also reported operation-ID collisions and many APIViews omitted from accurate serializer inference.

**Impact:** Frontend validation/types can disagree with the server, and generated clients may omit or misname privileged endpoints.

**Remediation:** Add explicit schema metadata/serializers, eliminate operation-ID collisions, regenerate the artifacts, review the diff, and keep the generated check mandatory after serializer changes.

## Detailed remediation playbook

This section turns the recommendations above into implementation tasks. Apply them in the order shown under **Fix order**; several schema changes depend on first removing authorization ambiguity.

### ZT-01 implementation — require explicit membership

**Code changes**

1. Delete the non-staff fallback at `core/rbac.py:124-131`. `workspace_membership()` must return `None` when no persisted `WorkspaceMembership` exists.
2. Remove the special implicit-user branch at `core/rbac.py:217-223`. `has_operator_capability()` should be equivalent to an explicit membership capability check; it must never substitute `ROLE_CAPABILITIES["owner"]`.
3. Keep staff/superuser bootstrap only as a temporary installation mechanism, or preferably replace it with an explicit initial-owner management command. The command should accept one user and workspace, run transactionally, refuse a second bootstrap, and create a real `WorkspaceMembership(role="owner")`.
4. Before deploying the code change, inventory legitimate users with no membership and require an administrator to assign each one deliberately. Do not write a data migration that grants every legacy user the default workspace.
5. Update the existing success case in `tests/test_webauthn_t1.py:243-278` to create an owner membership explicitly; otherwise that test preserves the vulnerability as expected behavior.

**Required tests**

- An authenticated, OTP-verified user with zero memberships gets 403 from a representative workspace read, `project.create`, `secret.create`, and T1 target deletion—even after a valid hardware touch.
- A user with a role in workspace A gets 404/403 for workspace B.
- Explicit viewer, deployer, admin, and owner memberships receive only the capabilities in `ROLE_CAPABILITIES`.
- Bootstrap creates one persisted owner and is idempotent/refuses conflicting users.

**Verification:** run the RBAC/isolation/auth suites, then `make test`; inspect the session/workspace payload to ensure no synthetic non-staff role is returned.

### ZT-02 implementation — confine or remove local source paths

**Code changes**

1. Add a production-default-off setting such as `HUB_ALLOW_LOCAL_SOURCES=False`. Reject `local_path` in `ProjectCreateSerializer` when it is off; Git should be the production API path.
2. If local sources are required, add a mandatory `HUB_LOCAL_SOURCE_ROOT`. Resolve both root and requested path with `Path.resolve(strict=True)` and require `candidate.is_relative_to(root)`. Reject the root itself, symlinked ancestors, device files, sockets, FIFOs, and paths not owned/readable by the dedicated source user.
3. Perform the same validation again in `wizard/hud_workers.py` and immediately before `_context_tar()`. Validation at request time alone is vulnerable to a path/symlink swap before worker execution.
4. Replace the permissive recursive archive with an allowlisted context builder. Honor a reviewed ignore file, cap individual and total bytes/file count, reject files that change inode/type while being read, and fail closed on read errors instead of silently producing a partial context.
5. Remove the vault-key mount from every worker that does not require decryption. In particular, no scanner/probe process should be able to select `/etc/deploy-hub` as source input. Longer term, give build workers an immutable checkout supplied by a fetch service rather than arbitrary filesystem access.

**Required tests**

- Refuse `/`, `/etc`, `/etc/deploy-hub`, `..` escapes, symlink escapes, a swap between validation and use, special files, and oversized contexts.
- Prove an allowed project beneath the configured root still scans and builds.
- Assert `vault.key`, `.env*`, VCS metadata, sockets, and secret-marker fixtures never appear in the tar member list.
- Assert Compose does not mount the KEK into probe/scanner workers.

### ZT-03 implementation — make findings tenant-native

**Schema and data migration**

1. Remove `default=default_workspace_id` from `Finding.workspace` and make callers supply it.
2. Remove `unique=True` from `Finding.fingerprint`; add `UniqueConstraint(fields=["workspace", "fingerprint"], name="finding_workspace_fingerprint_uniq")` plus an index supporting workspace/state/severity queries.
3. Add `workspace` to `AlertState` and replace its global fingerprint uniqueness with the same composite constraint. Any other fingerprint-keyed table/query must follow the same rule.
4. Write a two-stage migration. First add nullable workspace/composite fields and backfill only rows whose resource reference determines one workspace. Export ambiguous rows for operator review; do not silently assign them to `default`. After review, make workspace non-null and activate the new constraints.

**Service changes**

- Change the helper to `finding(source_engine, fingerprint, *, workspace, **fields)` so omission is a Python error.
- Filter both the optimistic lookup and the `IntegrityError` retry by `(workspace, fingerprint)`.
- Pass workspace from every producer, preferably from the owning `Site`, `Target`, `Partner`, or operation rather than a process-global default.
- Scope recurrence, stale-resolution, hysteresis, paging, audit, and realtime publication consistently.

**Required tests:** two workspaces may file the same fingerprint and receive separate rows/state; transitions in A cannot affect B; ambiguous historical rows block migration completion; concurrent filing remains idempotent per workspace.

### ZT-04 and ZT-10 implementation — tenant-correct, serialized audit chains

**Code and schema changes**

1. Make `workspace` mandatory in `audit()`, or implement a strict resolver for known object ownership paths that raises on ambiguity. Global platform events need an explicit `scope="system"` representation; they must not masquerade as default-workspace events.
2. Update all call sites. API paths should pass `request_workspace(request)`; workers should pass the operation/resource workspace loaded from the database.
3. Add `workspace_id`, `partner_id`, chain version, and any immutable scope identifier to `_canonical_row()`.
4. Introduce an `AuditChainHead` row per workspace/system scope. Within one `transaction.atomic()`, lock the head with `select_for_update()`, create the event with its predecessor hash, calculate/store the new chain hash, and update the head. A plain “last event” query cannot serialize concurrent writers.
5. Change `AuditEvent.workspace` from `CASCADE` to `PROTECT`, or retain an immutable workspace identifier/name with `SET_NULL`. Deleting a workspace must not delete its evidence.
6. Do not silently recompute the existing chain after changing the canonical format. Close the old chain with a signed/versioned checkpoint and start chain version 2, preserving the old bytes for verification.

**Required tests:** concurrent writers produce one linear chain; editing workspace/partner attribution breaks verification; workspace deletion retains audit rows; every representative tenant action appears only in the correct tenant export; ambiguous audit calls fail loudly.

### ZT-05 implementation — separate read and incident-management authority

1. Add `findings.manage` to operator, deployer, admin, and owner roles—not viewer/auditor unless policy explicitly grants it.
2. Map ack/resolve to `findings.manage`. Add a stronger `findings.accept_risk` capability for admin/owner and consider `RequireRecentTouch` for P1/P2 accept-risk.
3. Because one endpoint currently handles three actions, either split action-specific endpoints or perform permission selection only after serializer validation and before loading/mutating the finding. Never leave `finding.transition` mapped to `admin_read`.
4. Audit denied transitions as well as successful ones, including workspace, finding ID, requested transition, actor, and trusted client IP—never the accept-risk text if policy may place secrets in it.

**Required tests:** viewer/auditor GET succeeds but every transition returns 403; operator may ack/resolve; only the designated stronger role may accept risk; a user cannot transition another workspace's finding by ID.

### ZT-06 implementation — separate system and tenant administration

The preferred design is a distinct system authority because the current resources are global.

1. Add `RequireSystemAdmin`, backed by `is_superuser` initially or a persisted global-role model. It must not consult the selected workspace.
2. Apply it to the global partner kill switch and AWS credential-binding endpoints. Remove `RequireWorkspace` from authorization decisions for those global operations, while retaining an explicit system audit scope.
3. Hide global actions from tenant capability payloads and UI action lists. A tenant owner should not even receive an enabled global control.
4. If the intended product design is tenant-specific instead, add workspace ownership to `PartnerApiFlag` and AWS credential bindings, migrate rows, use composite uniqueness, and update all consumers to resolve credentials/flags through the resource workspace. Do not mix a global singleton with tenant-scoped authorization.

**Required tests:** owner of workspace A cannot affect a global flag or credential; system admin can; changes are system-audited; if resources become tenant-owned, changes in A have no effect in B.

### ZT-07 implementation — establish real worker boundaries

**Infrastructure changes**

1. Replace the shared `&hub-env` credential block with per-service DB and Redis principals. Use least-privilege Postgres grants/views and Redis ACL users restricted to the keys/channels/queues each process requires.
2. Remove `hub-vault` from probes and Beat immediately. Determine whether deploy/control workers truly need plaintext; where possible, expose narrow operations through a dedicated secret service instead of mounting the KEK.
3. Put worker classes on separate networks and prevent probe workers from reaching privileged providers/services they do not use.
4. Sign task envelopes with producer identity, task name, workspace/resource IDs, issued-at/expiry, and nonce. At execution, load the current operation/resource from the DB and reauthorize that it belongs to the claimed workspace before side effects.
5. Run workers under distinct non-root users with read-only filesystems, dropped Linux capabilities, `no-new-privileges`, resource limits, and no Docker socket.

**Verification:** add Compose-policy tests for mounts, users, networks, and credential separation; integration-test that probe credentials cannot read vault tables, publish to deploy/control queues, or decrypt secrets; replayed/tampered task envelopes must fail and create a security audit event.

### ZT-08 implementation — ship audit data to immutable storage

1. Add a provider interface such as `providers/audit_store.py` and a production S3 implementation using `PutObject` only. At startup/health check, verify bucket versioning and Object Lock retention; refuse to claim protection if either is absent.
2. Give the Hub an IAM principal limited to the audit prefix and required KMS key, with no delete, retention-reduction, or overwrite permission. Use unique keys containing workspace/system scope, monotonic sequence, and chain hash.
3. Add an idempotent Celery task and Beat schedule. Mark `shipped_at` only after the remote response is confirmed; retries must write the same content/key or safely detect an existing identical object.
4. Track oldest-unshipped age and last successful checkpoint. File/page on lag beyond the SLO and expose the degraded state in readiness.
5. Add an independent verifier that downloads a range, validates retention metadata and both local/remote chain continuity, and can run without trusting the Hub database.

**Required tests:** absent/misconfigured lock fails closed; retries are idempotent; partial failures leave rows pending; tampered/missing/reordered objects are detected; the shipping identity cannot delete an object.

### ZT-09 implementation — remediate Node advisories

1. Use Node 22 as declared by the sample workspace. Upgrade `fastify` to at least `5.8.3`, `ws` to at least `8.21.0`, and the sample Vite dependency to a release satisfying all audit fixes (at least `6.4.3` for the reported set). Regenerate `pnpm-lock.yaml` with the repository's declared pnpm version.
2. In `frontend/`, update the dependencies that resolve `js-yaml@4.3.0` and `nanoid@3.3.17`. The reported esbuild issue requires a supported Vite upgrade; treat the major-version jump as a reviewed change rather than running `npm audit fix --force` blindly.
3. Re-run sample TypeScript builds, scanner fixtures/mutations, WebSocket/ingest tests, frontend unit/E2E tests, and both package audits.
4. Add `npm audit --audit-level=high` and `pnpm audit --audit-level high` as mandatory gates. Document time-bound advisory waivers with package path, reachability, owner, and expiry.

### QG-01 implementation — make gate ordering structural

1. Add `.NOTPARALLEL: review-round nightly-gates` if the oldest supported GNU Make honors it as required, and add tests that invoke the aggregate with `-j`.
2. Independently extend the Makefile self-defense to reject `j`, `--jobs`, and jobserver flags for gate targets. This preserves fail-closed behavior when a parent Make injects parallelism through `MAKEFLAGS`.
3. Prefer explicit dependency edges or a serial gate driver over relying on the left-to-right spelling of sibling prerequisites. The required invariant is `green test -> mutation -> conformance reading that exact report`.
4. Add a test with fake timestamped gate commands proving mutation cannot start before tests finish and conformance cannot start before mutation finishes, under both direct and inherited `MAKEFLAGS` invocations.

### QG-02 implementation — repair and expand mutation evidence

**Baseline repairs**

1. Reproduce the clean-run FK error inside `mutants/` with the selected phase-1 test. Remove hard-coded/default workspace IDs from fixtures; create related `Workspace` and `DnsAccount` rows in the same database lifecycle and ensure teardown/cascade order satisfies constraints.
2. Fix the SQLite-sidecar gate failure by making the test enumerate the same declared sandbox inputs as `sandbox_files()`, including its Git-ignore policy. Do not hardcode only `-shm`; WAL, journal, coverage, and tool caches are the same class of runtime output.
3. Add `scanner/presentation.py` and `hub/renderers.py` to `GATE_BEARING` so the anti-narrowing floor matches the five configured modules.

**Scope expansion**

- Add security seams in small reviewed batches: `core/rbac.py`, `core/permissions.py`, `core/findings.py`, `core/audit.py`, `realtime/authorize.py`, privileged task dispatch, and vault boundary code.
- For each batch, derive the touching tests, run cold, kill non-equivalent survivors with failing-first tests, and record only genuinely equivalent mutants as individually justified waivers.
- Include a hash of the resolved Python environment—not only requirement source files—in the cache fingerprint, or run mutation in a locked container identical to CI.

**Acceptance:** the clean baseline passes, every configured mutant is killed/timed out or has a live justified waiver, zero mutants are unchecked, and a deliberate authorization mutation is proven to make the gate red.

### QG-03 implementation — gate frontend quality and browser checks

1. Add a `frontend-quality` Make target that runs `npm ci` in CI, ESLint, unit tests, and the production build through the package's `quality` script.
2. Add a stable `frontend-a11y` target for the six WCAG checks. Decide whether pixel snapshots block CI or require an explicit reviewed update; do not silently regenerate them in CI.
3. Make these targets prerequisites of `review-round` and invoke the same bare targets in `.github/workflows/push-checks.yml`. Install the pinned Playwright Chromium build before executing browser tests.
4. Preserve artifacts—trace, screenshot, and accessibility violation details—on failure.

### QG-04 implementation — cover every dependency and secret surface

1. Audit `requirements.txt` and `requirements-dev.txt`, `frontend/package-lock.json`, and `sample-node-site/pnpm-lock.yaml`. Run audits from locked, reproducible Python/Node versions.
2. Add a repository secret scanner that covers tracked and untracked working-tree files in local review and Git history/new commits in CI. Use narrow test-fixture allowlists with fake prefixes; do not exclude entire `tests`, `conformance`, or `scripts_dev` trees.
3. Keep the current targeted `SECRET_KEY` rule as an additional semantic check, not the primary secret scanner.
4. Fail on unsupported ecosystems/lockfiles so a new package manager cannot land outside the audit matrix.

### QG-05 implementation — restore generated-contract integrity

1. Give every warned APIView explicit request/response serializers or `@extend_schema` metadata. Assign unique stable operation IDs to collection/detail and target-command routes.
2. Run `make generate-client`, review the OpenAPI diff for auth requirements, workspace selectors, action inputs, and secret-bearing fields, then review TypeScript/Zod changes for unwanted optionality or omitted endpoints.
3. Update frontend consumers and contract fixtures to the regenerated schemas; do not commit generated output merely to make the diff gate green.
4. Run `make check-generated` from a clean tree twice. The first run must produce no diff and the second proves idempotence.

### Mechanical gate-failure repairs

- **T1 SQLite sidecar:** unify the mutation sandbox and test enumeration as described under QG-02, then prove runs are green both with and without SQLite WAL/SHM files present.
- **Mutation FK baseline:** fix fixture ownership/lifecycle before interpreting any mutant result; delete the invalid cache only through `make mutation`'s fingerprint path, then require a cold complete run.
- **T3:** restore the Multipass daemon/socket and confirm `multipass list` plus a disposable guarded launch work. Re-run `make test-all` once; then run `make conformance-3` against that same full report. Do not replace it with separate narrowed sessions.
- **Phase 7:** obtain the real named-partner evidence required by `PART-U1-NAMED-PARTNER`, or formally defer/waive it through project policy. Do not create a synthetic demo artifact.
- **Generated client:** complete QG-05 in the dirty feature branch before using `check-generated` as release evidence.

## Fix order

1. **Immediate containment:** remove implicit membership authority; disable production `local_path`; restrict global kill-switch/AWS endpoints to system admin; upgrade Fastify/`ws`.
2. **Tenant integrity:** migrate findings/alert state; require explicit audit workspace; split finding-management capabilities.
3. **Tamper resistance and blast radius:** serialize/version audit chains, ship them off-host, split worker credentials/mounts/networks.
4. **Evidence repair:** fix the T1 sidecar and mutation FK baselines, stale generated artifacts, and Make parallelism.
5. **Release proof:** run the full serial gate matrix on Python 3.12/Node 22, restore Multipass for T3, complete conformance, and retain the raw reports.

Each stage should land independently with migrations and rollback notes. Do not combine tenant data migrations, authorization changes, worker credential rotation, and dependency major upgrades into one deployment.

## Strengths observed

- Production fails closed on a missing secret key, fake KEK, insecure WebAuthn origin, and test-mode activation.
- Session authentication, login CSRF protection, secure cookies/HSTS under `hub.settings.prod`, and mandatory HTTP 2FA are present. The documented loopback Compose settings intentionally relax the cookie/redirect flags.
- T1 actions use recent hardware touch, two-passkey enrollment, short freshness windows, and typed confirmation.
- WebSockets validate origin/session/OTP/topic and check object-topic membership.
- Partner Ed25519 verification covers method, path, body, freshness, replay nonce, idempotency, and Hub-side quota checks.
- Signed downloads are TTL-, actor-, workspace-, and deployment-bound.
- Celery accepts JSON only; Redis is internal and password protected.
- Workspace-scoped queryset helpers are widely used and foreign IDs commonly return 404.
- The mutation wrapper itself fails closed on unknown/unchecked outcomes; the current red verdict is honest.

## Release criteria

At minimum, do not call the build zero-trust-ready until:

1. ZT-01 through ZT-06 are fixed with multi-workspace and zero-membership regression tests.
2. The T1 suite is green without ignoring runtime files, and the mutation clean baseline passes.
3. Mutation produces a complete verdict for all configured mutants and expands to RBAC/tenant boundaries.
4. Generated API artifacts are current and schema warnings affecting privileged endpoints are resolved.
5. Runtime Node vulnerabilities are upgraded and JS audits are gated.
6. A functioning Multipass host completes T3, then `make conformance-3` passes from that same all-tier report.
7. Phase-7 named-partner evidence is supplied or the requirement is formally deferred/waived according to project policy.
8. Production audit shipping and meaningful worker credential isolation are implemented and exercised.

## Reproduction commands

```bash
source .venv/bin/activate
make lint
make log-scrub
make scripts-lint
make test
(cd frontend && npm run quality)
(cd frontend && npm run test:e2e)
make mutation
make conformance
make conformance-7
make test-all
make conformance-3
(cd frontend && npm audit --audit-level=low)
(cd sample-node-site && pnpm audit --audit-level low)
```

Run Make gates serially. Do not substitute separate T1/T2/T3 sessions for `make test-all`, because each narrowed session overwrites the conformance run report.
