# Phase 0 Design Note — Skeleton + Seams

**Phase:** 0 (per plan-addendum-2026-07-30.md §I, as patched by plan-addendum-2026-08-02-review3.md)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-02
**Repo:** `~/Documents/deploy-hub` (Joseph's Mac; permanent git home TBD — see DECISIONS.md D-001)

---

## 1. What lands this phase

Phase 0 exists to make every later phase cheap: the seams, contracts, and process
machinery are laid down before any product feature depends on them. Deliverables:

1. **Compose stack** — Postgres 16, Redis 7 (hardened per §B4: compose-internal network
   only, `requirepass` generated, no published port), Django web, Celery workers split
   into the three queues from day one (`deploys` / `probes` / `control`), Celery Beat.
2. **App layout (§D4)** — `hub/` settings pkg + `core/ vault/ catalog/ scanner/ provision/
   deploys/ reconcile/ providers/ monitor/ scaling/ realtime/`. The import rule
   (cloud/DNS SDK imports only under `providers/`) is enforced by a grep test from the
   first commit.
3. **Auth** — Django session login (HttpOnly/Secure/SameSite=Lax + CSRF header, §A1)
   with **TOTP** second factor (django-otp). WebAuthn deferred to Phase 4 per §E9;
   interim risk accepted and recorded (Hub is Tailscale-only from day one).
4. **Realtime contract (§D7)** — one `EventsConsumer` (session-auth at connect,
   reject anonymous), `{action: subscribe|unsubscribe, topics: []}` protocol, every
   subscribe through the single `authorize_topic(user, topic)` choke point,
   `publish(topic, event)` helper doing `INCR evt:seq:{topic}` + `group_send`,
   snapshot endpoints returning `{seq, data}`. Proven by the **demo job**: a Celery
   task streaming fake deploy logs end-to-end (Celery → Redis → Channels → React panel).
5. **Validation pipeline (§4.5) on the first form** — DRF serializer as source of
   truth, drf-spectacular schema, generated TS client + zod schemas, react-hook-form
   wiring, the `{field: [{code, message, hint}]}` error shape and `confirm_warnings`
   flag. First form = the demo-job launch form (name + fake duration), deliberately
   trivial so the pipeline is the deliverable.
6. **Seams + fakes (§A7/§D5)** — `Transport` interface (run/put/get) with `FakeTransport`
   and `RecordingTransport`; `providers/base.py` with `DnsProvider`, `EdgeProtection`,
   `CloudProvider` interfaces and `providers/fakes.py` in-memory implementations.
   No real SSH/cloud code this phase — the seams exist so T1 tests are possible
   from the first feature.
7. **AuditEvent + `audit()` helper (§D1)** — append-only model with the pinned schema,
   including the Phase-5.5 early stub: nullable `partner` FK-shaped column
   (IntegerField placeholder until a Partner model exists) and `partner` tier value
   reserved in the tier enum. Off-host shipping is Phase 4; the model and helper are now.
8. **Conformance tree (review3 §Q1–Q2)** — `conformance/requirements.yaml` (starter
   registry), `schema.json`, `paths.yaml` (sensitive-path globs incl. `scripts/**`,
   `intake/**`, `conformance/requirements.yaml`), `check.py`, `demos/`. CI job
   `conformance-check` red on unmarked phase-due reqs or unknown markers.
9. **CI workflows 1–2** — on-push: ruff, bandit, pip-audit, eslint/tsc, log-scrubber
   grep, T1 unit (<2 min), conformance-check; container-tier T2 job stubbed (lands
   fully in Phase 2.5).
10. **Simulation-mode seed v0 (§F8)** — fixture JSON (2 zones, 4 targets, 6 sites) +
    an event replayer that publishes scripted events through the real Channels path.
    v0 = seed loads + replayer drives the demo log panel.
11. **Process artifacts** — `REVIEW_CHECKLIST.md` (v1, req-ids inline), `DECISIONS.md`,
    `WAIVERS.md`, `tests/acceptance/test_phase_0.py` with `@pytest.mark.acceptance(phase=0)`.

## 2. Interfaces / tables that change

New tables: `core.AuditEvent` only (plus Django auth + django-otp device tables).
Product models (Target, Site, …) are **deliberately not created** in Phase 0 — they
land with the features that own them, so migrations stay honest.
New interfaces (code, no DB): `Transport`, `DnsProvider`, `EdgeProtection`,
`CloudProvider`, `authorize_topic`, `publish`, `audit`.

## 3. Applicable addendum items

§A1 (session auth) · §A7 (test seams) · §A8 (shadcn/Tailwind — scaffolded, components
added as screens appear) · §B4 (Redis hardening) · §D1 (AuditEvent) · §D4 (layout) ·
§D5 (provider interfaces) · §D7 (realtime contract) · §F8 (simulation mode) ·
review3 §Q1–Q6 (conformance machinery, mechanical teeth) · §K9 early stubs.

## 4. Exit demo (the milestone *is* a test)

From a clean checkout: `docker compose up` → log in (password + TOTP) → open the
demo panel → launch the demo job from the validated form → live log lines stream
into the panel over the multiplexed socket → kill the socket (devtools) → reconnect
recovers via snapshot-then-stream with no gap. Recorded in
`conformance/demos/phase-0.md`; `check.py --phase 0` green; acceptance tests green in CI.

## 5. DECISION markers opened

- **D-001** repo permanent home: local folder now; GitHub private repo required no
  later than Phase 2.5 (CI is load-bearing then). Reversible; revisit at Phase 1 exit.
- **D-002** TS client generation tool (openapi-typescript vs openapi-zod-client):
  Researcher decides by §4.5 criteria during build; either is swappable behind the
  generated-artifacts directory.
- **J-1** (from addendum §J) integration-tier fidelity spike is scheduled inside
  Phase 0 as a half-day: sshd+systemd container vs Multipass boundary for T2.

## 6. Out of scope (explicitly)

Any SSH to real machines · scanner logic · provisioner/catalog entries · WebAuthn ·
map/monitoring UI · partner intake. Anything resembling these appearing in a Phase 0
diff is a round finding.
