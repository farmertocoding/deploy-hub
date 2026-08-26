# Phase 7.4 Design Note — Hub-central DNS-01 (T1 Fake)

**Phase:** 7.4 leftover of addendum §B2 / Phase 4 named first slip (`TLS-B2-HUB-DNS01-UNPROXIED`)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-26 · **Seat:** Grok 4.6
**Revision:** r1 — T1 Fake issue + Beat renew. Binding §7.
**Estimate:** hours-to-a-day. Protective cut: **D-136**. Phase 7.3 previews are on `master` @ `4cb470e`. Live Let's Encrypt, inventing `HUB_TEST_CF_TOKEN`, Pulumi, Azure, HMAC enablement, U1 are **not this wave**.
**Schema:** none. `TlsCertificate.Mode.HUB_DNS01` and `CheckRun.Kind.HUB_DNS01` already exist (`0009`). `0015` stays closed.
**Panel:** §7 is binding. Expert team continue (Joseph delegated commit/merge/push).

## 1. What lands this wave

Addendum §B2 forbids Caddy-does-DNS-01: a zone-scoped token on a target can repoint the zone. Proxied sites already get Origin certificates. Unproxied public sites still refuse. This wave issues on the Hub, upserts `_acme-challenge` via the existing `DnsProvider`, and pushes PEM the same atomic path as Origin certs. Live ACME stays skip-unless.

### 1.1 MUST

1. **Issue.** `deploys/dns01.py::issue_unproxied(desired, *, dns01=None)` — unproxied public only. `dns01 is None` → `Dns01Error("dns01 refused")` and the existing Finding `unproxied-cert:{pk}` (never a bare exception). Injected `dns01(hostnames, csr, dns)` upserts TXT via `desired["dns"]`, returns `{certificate, expires_at}` (Fake uses `mint_local_leaf`). Then the existing put/chmod/mv + Caddy reload. `TlsCertificate.mode=hub_dns01`. Resolve OPEN/ACKED `unproxied-cert:{pk}`. ACCEPTED stays. Do **not** call Origin CA. mesh_only / proxied unchanged.

2. **Wire.** `ensure_site_certificate` calls `issue_unproxied` instead of `_refuse_unproxied` for unproxied public. Production seams still fail-closed: no `FakeDnsProvider` from `resolve_production_seams`. Tests wrap `deploys.certs.issue_unproxied` / `deploys.dns01.issue_unproxied`.

3. **Renew Beat.** `renew_due(*, now=None, issue=None)` walks `mode=hub_dns01` rows inside `RENEW_BEFORE_DAYS` and calls `ensure_site_certificate`. Beat `hub-dns01-renew-daily` (86400 s, queue `probes`) writes `CheckRun.Kind.HUB_DNS01`. No secret in task args.

4. **Honesty / gates.** Everyday `conformance` stays phase 5 minus live. `TLS-B2-HUB-DNS01-UNPROXIED` stays **waived** until Task 2 proofs (do not hostage T1 merges). New MUST id `P7-DNS01-DEMO` phase 7, tier-less, `verify: demo`. Claim `deploys/dns01.py` only. Do not waive U1. Do not stub `named-partner.md`. Do not invent `HUB_TEST_*`. AST: no ACME DNS block in generated Caddy; no DNS token on a target-bound surface.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| T1 Fake Hub-central DNS-01 + push PEM + resolve refusal Finding | **MUST** |
| Beat renew of `hub_dns01` rows | **MUST** |
| Live Let's Encrypt / certbot / Caddy DNS-01 on the target | **OUT** |
| Invent `HUB_TEST_CF_TOKEN` / retire `HARNESS-T3-LE-STAGING` | **OUT** |
| Pulumi / Azure / U1 / HMAC enablement | Unchanged park |

## 2. Interfaces that change

**Python:** `deploys/dns01.py` (new). `deploys/certs.py` (unproxied branch). Beat schedule + `monitor/tasks.py` one wrapper. Acceptance invert of the slip pin. Append `conformance/demos/phase-7.md`. README honesty.

**Not changed:** Origin CA path. `0015`. Findings.jsx / Chrome.jsx. Caddy ACME. Live CF token env. `providers/cloudflare.py` ACME client.

## 3. Applicable registry reqs

Task 0 — one new MUST id, phase 7, no `tier:`. `source: phase-7.4-design-note.md §3`. `--print-text-hashes`. Extend `PHASE_7_MUST_IDS` + `allowed_sources`. Subtract `P7-DNS01-DEMO` from `PHASE_7_TEST_IDS`. Do not rewrite `TLS-B2-HUB-DNS01-UNPROXIED` `text:` until Task 2 retires the waiver.

- `P7-DNS01-DEMO` — `phase: 7`, `verify: demo`, `demo: conformance/demos/phase-7.md`. `text:` unproxied public site, injected dns01, Hub upserts TXT and pushes PEM mode hub_dns01; missing inject refuses with Finding unproxied-cert; Beat renew_due reissues due rows; no live Let's Encrypt; token never on the target.

Task 2 marks existing `TLS-B2-HUB-DNS01-UNPROXIED` on the issue/refuse/renew tests and rewrites its `text:` to drop the “until it is built” clause.

## 4. Exit demo

Unproxied public Site + injected `dns01` → `ensure_site_certificate` issues, `TlsCertificate.mode=hub_dns01`, `unproxied-cert:{pk}` RESOLVED, transport put of cert.pem/key.pem only (no token). Missing inject → Finding + `Dns01Error`. `renew_due` on a row inside `RENEW_BEFORE_DAYS` issues again. Record: append `conformance/demos/phase-7.md`. Honest: no live LE, no `HUB_TEST_CF_TOKEN`, no Caddy DNS-01, no U1.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-136** Protective cut — T1 Fake Hub-central DNS-01 + Beat renew. Live ACME / Caddy-on-target DNS-01 / inventing `HUB_TEST_CF_TOKEN` are OUT.
- **D-137** No new migration. Reuse `hub_dns01` mode + `HUB_DNS01` CheckRun kind. HTTP stays out of `core/views.py`. Module is `deploys/dns01.py`.
- **D-138** Everyday gates stay phase 5 minus live. `TLS-B2` waiver stays until Task 2. New demo id phase 7. U1 stays uncovered. Claim `deploys/dns01.py` only.
- **D-139** Live LE-staging waiver (`HARNESS-T3-LE-STAGING`) stays. Pulumi/Azure/U1/HMAC parks unchanged.

## 6. Protective cut (D-136)

MUST = Fake issue + push + resolve Finding + Beat renew + park live LE. Live ACME and token-on-target are **OUT**.

## 7. Closed contract (binding)

**C1 Issue.** Unproxied public + injected `dns01` + `desired["dns"]` → one `hub_dns01` row + PEM push. Never Origin CA. Never `run_deploy`.

**C2 Refuse.** Missing inject / missing dns → Finding `unproxied-cert:{pk}` + `Dns01Error`. Never a bare exception. Production seams do not construct a Fake.

**C3 Renew.** Beat `hub-dns01-renew-daily` / `renew_due`. `CheckRun.HUB_DNS01`. No secret args.

**C4 Surfaces.** No ACME DNS block in generated Caddy. Existing target-bound token scan stays green.

**C5 UI.** `CertState` still paints an open refusal; after issue `cert_refusal` is null. NAV six. Do not edit Findings.jsx / Chrome.jsx.

**C6 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P7-DNS01-DEMO` on pytest. Do not mark `TLS-B2` until Task 2.

**C7 Schema.** No new columns. `0015` closed.

**C8 Gate.** conformance-7 verifies `P7-DNS01-DEMO`; after Task 2 `TLS-B2` is verified and the waiver is retired. U1 uncovered-only allowed.
