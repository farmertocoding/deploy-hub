# Deploy Hub Design Concepts — Functional Screen Contract

This contract turns the design concepts into operational screens. Nothing is clickable merely because it looks interactive. Every button, link, filter, card, status, chart, and table value must either help an operator make a decision or complete a defined task.

The four mockups are visual references. This document is the behavioral source of truth for them.

## 1. Rules shared by every screen

### Every interactive control must have six properties

1. **Purpose:** the user problem it solves.
2. **Destination or effect:** the page, drawer, download, or server command it produces.
3. **Permission:** the capability required to use it.
4. **Availability:** the exact states in which it is enabled or disabled.
5. **Feedback:** loading, success, failure, conflict, and degraded behavior.
6. **Audit outcome:** whether use of the control creates an audit event.

If any property is undefined, the control must not appear in the product.

### Display rules

- A number always includes its scope: `3 blockers`, not `3`.
- A status always uses a word and symbol; color alone is insufficient.
- A timestamp identifies freshness or uses a tooltip with the exact time.
- A chart has an accessible data table and an explicit time range.
- A metric card is not implicitly clickable. It contains a labelled navigation link when drill-down exists.
- Empty space is not filled with decorative charts. A panel exists only when it changes a decision or shortens a task.
- Realtime data shows `LIVE`, `RECONNECTING`, or `DATA AS OF <time>`.
- Buttons never acknowledge passive behavior. For example, `Keep watching` is not an operation and must not be a button.

### Mutation rules

- One primary mutation per page or focused panel.
- Read-only navigation never looks like a destructive or primary mutation.
- Duplicate submissions are prevented with an idempotency key.
- Accepted commands return an operation or deployment ID immediately.
- T2 actions show an exact before → after diff and server-computed impact.
- T1 actions require typed object identity, recent WebAuthn verification, and an impact plan.
- Disabled actions remain visible with a reason.
- No deployment record can be deleted from the interface.

## 2. Global shell contract

| Control/display | Actual use | Behavior and implementation contract |
|---|---|---|
| Left navigation | Move between operational domains | Routes to the selected collection. Current location is visually and programmatically selected. |
| Breadcrumbs | Preserve location and parent navigation | Every ancestor except the current page is a link. No mutation. |
| `PRODUCTION` scope | Show or change the current environment scope | Opens a scope selector. Changing scope refreshes all queries and is preserved in the URL. It never deploys anything. |
| Global search | Find a project, site/domain, target, deployment ID, finding fingerprint, or partner | Debounced server search with grouped results and keyboard navigation. Selecting a result opens its detail page. |
| `LIVE` | Explain realtime connection state | Opens a small connection-status popover showing transport, last event, and last successful refresh. It is not a decorative badge. |
| `3 P1/P2` | Reach urgent findings | Opens Findings filtered to open P1 and P2 records in the current scope. |
| Notification bell | Track asynchronous work | Opens the operation drawer with running, completed, failed, and refused commands. Unread count clears only after the drawer is viewed. |
| User/role menu | Reach personal security and authorized administration | Opens Profile, Security, Administration, and Sign out. Options are permission-filtered. |

## 3. Concept 01 — Fleet Overview

Current image: `01-fleet-overview-hud-dark-v3.png`

### Operator job

Answer three questions within seconds:

1. Is anything affecting users now?
2. Is any deployment stuck or failing?
3. What is the highest-priority safe next task?

### Displays

| Display | Actual use | Data contract |
|---|---|---|
| Attention required | Quantifies open deploy-blocking or user-impacting findings | Count of open P1/P2 findings after workspace and environment authorization filters. |
| Deployments | Shows current deployment workload | Counts queued, waiting-for-lock, and running deployments. Never inferred from frontend state. |
| Sites | Shows desired-versus-observed fleet health | Counts healthy, warming, unhealthy, and stale sites using the most recent reconciler observation. |
| Targets | Shows placement capacity and host risk | Counts ready, pressured, unreachable, and decommissioned targets. |
| Deployment activity chart | Detects abnormal failure or queue patterns | Time-bucketed deployment outcomes with a visible range and accessible table. |
| Active deployment rows | Lets operators enter ongoing work quickly | Deployment ID, site, current step, elapsed time, heartbeat, and status from the deployment read model. |
| Attention queue | Orders urgent work | Server-ranked findings; priority, object, plain-language impact, and age are required. |
| Fleet health | Compares site-state distribution | Uses the same status definitions as the Sites table; no separate dashboard-only calculation. |
| Integrations | Reveals control-plane dependencies | Last verified state for AWS, Cloudflare, Vault, notification delivery, and other configured integrations. |
| First-run checklist | Completes setup that is still blocking safe operation | Appears only while at least one required setup task is incomplete, then disappears. |

### Controls

| Control | Destination/effect | Permission and state |
|---|---|---|
| `ADD APPLICATION` | Starts the Project + first Site wizard | `project.create`; disabled when no writable workspace exists. |
| `View attention queue` | Findings filtered to open P1/P2 | Any read role. |
| `View deployments` | Deployments filtered to active states | Any read role. |
| `View sites` | Sites collection with the corresponding health filter | Any read role. |
| `View targets` | Targets collection with readiness filter | Any read role. |
| Active deployment row | Opens that Deployment detail | Any read role. |
| `REVIEW` | Opens the selected Finding detail | Any read role; remediation actions on the next page require separate authorization. |
| `View fleet health` | Opens Sites with health facets visible | Any read role. |
| `View integrations` | Opens Integrations | Admin/Owner for credential mutations; read-only metadata may be available to Auditor. |
| `FINISH SETUP` | Opens the first incomplete setup task | Admin/Owner. Server selects the task; it never silently changes configuration. |

No dashboard card mutates fleet state.

## 4. Concept 02 — Sites Fleet

Current image: `02-sites-fleet-hud-light-v3.png`

### Operator job

Find a Site, understand whether desired state matches live state, and take the one appropriate next action without opening several pages.

### Displays

| Display | Actual use | Data contract |
|---|---|---|
| Site/project | Establishes deployable object and source ownership | Site name plus parent Project. |
| Environment | Separates production, staging, and previews | Immutable environment class for filtering and policy. |
| Domain | Identifies user-facing route | Canonical domain and exposure state. |
| Health | Shows observed serving health | Latest reconciled health with observation timestamp. |
| Live → desired | Reveals release drift | Currently routed Release and desired approved Release. |
| Target | Shows placement | Primary Target plus running-copy count when space allows. |
| Deployment | Shows active command and current/failed step | Derived from active Deployment and its newest Step event. |
| TLS/backup | Exposes two common production risks | Certificate expiry and newest valid backup age. |
| Updated | Establishes data freshness | Newest authoritative observation, not last frontend refresh. |
| Selected-Site inspector | Supports comparison without losing table position | Reads the same Site record and active Deployment shown in the selected row. |

### Controls

| Control | Destination/effect | Permission and state |
|---|---|---|
| `ADD SITE` | Starts a Site creation wizard under a selected or newly chosen Project | `site.create`. Requires at least one compatible Target or offers a setup path. |
| `ALL`, `NEEDS ATTENTION`, `ACTIVE DEPLOY` | Applies mutually exclusive server filters | Any read role. Counts come from the same filtered query. |
| Search | Filters by Site, domain, and Project | Any read role; query is represented in the URL. |
| Environment/Health/Target/TLS filters | Narrows the collection | Any read role. Multiple filters compose with AND semantics. |
| `CLEAR` | Removes all collection filters | Enabled only when a filter or query is active. |
| `EXPORT VIEW` | Creates a CSV export of the authorized filtered result | Auditor/Admin/Owner. Async for large result sets; audit event records filters and row count. |
| Sortable headers | Changes server ordering | Any read role. Current sort is visible and stored in the URL. |
| `FIX BLOCKERS` | Opens blocking Findings for that Site | Visible when blockers exist; never runs remediation automatically. |
| `VIEW DEPLOY` / `VIEW DEPLOYMENT` | Opens the active Deployment | Visible only when an active or attention-required Deployment exists. |
| `DEPLOY` | Opens preflight for the approved desired Release | Deployer/Admin/Owner; disabled with a visible reason when blocked, locked, or no approved release exists. |
| Row `MORE` | Opens text-labelled contextual actions | Includes Edit configuration, Rescan, Clone environment, Preview, Pause automation, and Archive only when allowed. |
| `OPEN LIVE SITE` | Opens the canonical domain in a new tab | Any read role; disabled if no healthy route is known. |
| `VIEW SITE DETAILS` | Opens full Site detail | Any read role. |
| Pagination | Requests the next authorized server page | Any read role; preserves filters and selection where possible. |

The row action is selected from server-returned `allowed_actions`; the frontend does not guess which action is safe.

## 5. Concept 03 — Live Deployment

Current image: `03-live-deployment-hud-dark-v3.png`

### Operator job

Answer what is affected, what is still serving, what step is running, whether users are impacted, and what safe recovery is available.

### Displays

| Display | Actual use | Data contract |
|---|---|---|
| Impact banner | States user effect before technical details | Server-computed impact classification with evidence and freshness. |
| Nine-step timeline | Shows the exact deployment lifecycle | Immutable Step attempts with state, start/end, duration, logs, and artifacts. |
| Current step checks | Shows why a step is still running or can pass | Structured check results, attempt count, next retry, and raw-event link. |
| Current state | Compares live and desired Release, Target, trigger, actor, policy, and Manifest | Snapshot stored on Deployment creation; not mutable Site data read after the fact. |
| Topology strip | Shows traffic position | Derived from serving route observation and green instance readiness. |
| Safest next action | Gives a server-recommended action and its reason | Recommendation endpoint returns action, reason, allowed capabilities, and impact plan. |
| Events & signals | Supports incident reconstruction | Ordered event stream with exact timestamps and correlation IDs. |

### Controls

| Control | Destination/effect | Permission and state |
|---|---|---|
| `OPEN LIVE SITE` | Opens the currently serving route | Any read role; warns if observed state indicates possible user impact. |
| `COPY ID` | Copies the immutable Deployment ID | Any read role; changes label to `Copied ✓`. |
| `MORE ACTIONS` | Opens only valid lifecycle actions | May include cancel queued, retry failed step, rollback to a named Release, or download logs. Never includes Delete. |
| Step row | Expands/collapses attempt details | Any read role. It is a disclosure control, not a mutation. |
| `VIEW LIVE LOG` | Opens a streaming log drawer for the selected step | Any read role with log permission; supports pause, search, and download. |
| `VIEW ARTIFACTS` | Opens immutable artifacts for the selected step | Any read role with artifact permission; downloads are named by type and format. |
| `VIEW SITE HEALTH` | Opens live Site health metrics and check evidence | Any read role. This replaces the non-operational `KEEP WATCHING` control. |
| `ABORT AND CLEAN UP` | Starts a new cleanup command while preserving history and volumes | Operator/Admin/Owner when the deployment is abortable. T2 confirmation shows resources removed and resources preserved. |
| `VIEW FULL AUDIT TRAIL` | Opens audit events filtered to this Deployment | Auditor/Admin/Owner, or read roles according to workspace policy. |

The page continues receiving events automatically. There is no `Keep watching`, `OK`, or `Acknowledge` button that performs no work.

## 6. Concept 04 — Access & Secrets

Current image: `04-access-secrets-hud-light-v3.png`

### Administrator job

Manage access and secret lifecycles without exposing secret material or hiding dependency risk.

### Displays

| Display | Actual use | Data contract |
|---|---|---|
| Vault health | Shows whether encrypted records and references are structurally valid | Count of active secrets, orphaned owner references, decryptability checks, and Vault service health. |
| Rotation due | Prioritizes expiring or policy-overdue credentials | Server policy evaluation per active secret version. |
| Active references | Shows blast radius | Count of authorized Project, Site, Target, DNS, and integration references. |
| KEK | Shows encryption-key lifecycle metadata | KEK identifier and age only; never key material. |
| Secret inventory | Locates credentials by type and owner | Metadata-only records with active version, safe fingerprint, last used, rotation, and reference health. |
| Selected secret | Explains one credential and its dependencies | Metadata and authorized dependency graph only. |
| Security policy | Verifies enforced controls | Actual policy evaluation, not static checklist copy. |

### Controls

| Control | Destination/effect | Permission and state |
|---|---|---|
| `ADD SECRET` | Starts a kind-specific secret wizard | Admin/Owner or delegated Secrets capability. The value is accepted once over a protected input and is never returned. |
| `INVITE USER` | Starts membership invitation | Admin/Owner; final submit creates an audit event and time-limited invitation. |
| Members/Roles/Vault/Sessions/Security tabs | Switches administration domain | Permission-filtered routes; selected tab is stored in the URL. |
| Search and Kind/Owner/Status filters | Narrows metadata inventory | Authorized metadata only. Searching never matches plaintext secret values. |
| `ROTATE` / `ROTATE SECRET` | Creates and validates a new version, then activates it according to policy | Secrets capability. Shows affected objects and validation result; production rotation may require T1 verification. |
| `VIEW` | Opens secret metadata detail | Never reveals ciphertext, wrapped DEK, nonce, plaintext, or a private URL. |
| Row `MORE` | Opens allowed lifecycle actions | Assign, retire version, export only if explicitly exportable, or delete an unreferenced retired version. |
| `REPLACE` | Creates a new version from supplied credential material | Secrets capability; old version remains available for controlled rollback until retirement policy allows removal. |
| `VIEW AUDIT HISTORY` | Opens audit events for this secret | Auditor/Admin/Owner. Values remain redacted. |
| `REVIEW ROTATION PLAN` | Opens rotation queue sorted by due date and dependency risk | Secrets capability or Auditor read-only access. |
| Pagination | Requests the next metadata page | Preserves authorized filters. |

There is no global Upload page. A secret, certificate, SSH key, or configuration artifact is uploaded only inside the wizard for the object that will own it.

## 7. Required backend response fields

To keep the UI truthful, every detail and collection response should include:

- `allowed_actions`: server-authorized actions for the current user and object state.
- `disabled_actions`: action plus machine-readable and human-readable refusal reason.
- `observed_at`: freshness of the displayed operational state.
- `version` or ETag: optimistic concurrency token.
- `active_operation_id`: current mutation/command when present.
- `impact_summary`: user-facing impact classification and evidence.
- `links`: canonical routes to related Project, Site, Target, Release, Deployment, Finding, and audit records.

Command endpoints should return `202 Accepted` with:

- Operation or Deployment ID.
- Idempotency key.
- Initial state.
- Status URL.
- Realtime subscription topic.
- Server-computed impact plan.

## 8. Design acceptance checklist

A concept is ready for implementation only when all answers are **yes**:

- Does every panel answer a real operator or administrator question?
- Does every button have a destination or server-side effect?
- Is every mutation permission-checked by the backend?
- Is every destructive/disruptive action given the correct friction tier?
- Can the user tell what is live, desired, running, blocked, and stale?
- Can the user tell when the displayed data was last observed?
- Do loading, empty, error, offline, permission, conflict, and busy states exist?
- Is the safest next action derived from current server state?
- Are logs, artifacts, and audit history preserved?
- Are secrets represented only by safe metadata?
- Can the interface explain why an action is disabled or refused?
- Is there a genuine operation behind every visually interactive element?

If the last answer is no, remove the element from the design.
