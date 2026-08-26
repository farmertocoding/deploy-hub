# Phase 7 exit demo — recorded (P7-RESTORE-DEMO)

**Date:** 2026-08-25 · **Branch:** `master` · **Recorded by:** Phase 7.0
Task 2. **T1 inject only.** This is not a live docker overwrite, live
AWS, named committed partner, or Playwright success. No KEK was used.
No live volume was overwritten. No new token env was added.

## What the milestone asked (design note §4)

A site with a sealed dump, T1 touch + type-the-name, injected
`restore_to_clean` → 201 ok; `RESTORE_CLEAN` CheckRun metadata has
`unit_id` and `checkrun_pk`; response has no dump bytes; live
SiteInstance untouched; command block still on GET list. Wrong confirm
→ 4xx. Missing dump → 4xx and `backup-restore-failed`. Unseal uses
`BACKUP_KEY`, never the KEK.

Record: `conformance/demos/phase-7.md`. This record **does not claim**
live docker overwrite, a KEK restore, Azure, preview
environments, LAN ghosts, Pulumi, or U1. `PART-U1-NAMED-PARTNER` stays
uncovered until Joseph writes `conformance/demos/named-partner.md`.
Everyday `make review-round` (phase 5) may go green while U1 is
uncovered. This session did not run `make review-round` or two
consecutive `make conformance-7` rounds; those gates re-earn green from
a fresh run-report. `make conformance-7` is the phase gate and
**excludes t2/t3**:
`python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3`.
No invented token env. No Playwright.

## The honest state of this host

T1. Inject actually driven this session:

- `restore_to_clean=` wrap on `provision.views.restore_to_clean` (HTTP)
  and the same inject on `provision.backup.restore_to_clean` (direct).
  Default primitive writes a tempfile and deletes it. No live docker.

`HUB_TEST_MODE` is off unless a test flips it. No invented token env.
NAV is still six.

## Still outstanding — named, not greened

- `PART-U1-NAMED-PARTNER` stays uncovered. `conformance/demos/named-partner.md`
  is absent. This record does not claim a named committed partner.
- Preview environments (private repos), LAN discovery
  ghosts, Pulumi/managed-DB/LB, Azure adapter, overwrite-live restore
  are later Phase 7 polish, not this wave.
- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2
  --exclude-tier t3`. `conformance-7` is not a `review-round` or
  `nightly-gates` prereq.

## Acceptance transcription — real nodeids

`tests/acceptance/test_phase_7.py` (`@pytest.mark.acceptance(phase=7)`),
each body calls the Task 1 proof:

- `test_restore_into_clean_container_t1`
- `test_restore_command_block_remains`
- `test_nav_stays_six`
- `test_demo_does_not_claim_live_docker_or_kek`
- `test_tunnel_nothing_forwarded_files_and_resolves`
- `test_router_advice_target_tab`

## Phase 7.1 — Router Advisor (P7-ROUTER-DEMO)

**Date:** 2026-08-26 · **Branch:** `master` · **Recorded by:** Phase 7.1
Task 2. **T1 inject only.** Injected `wan_probe` — not live UPnP, not a
live WAN scan. This session did not run a live UPnP discovery or a live
WAN scan. No model-tailored steps. No Playwright.

### What the milestone asked (design note §4)

Tunnel-mode SSH target, injected `wan_probe` returning one
`{port: 443, proto: tcp}` → Finding OPEN `router-forwarded:{pk}`; GET
detail `router_advice.finding_id` set; T3 POST **Probe router** with
empty forwards → Finding RESOLVED; GET detail `finding_id` null.
Missing inject → 4xx `wan probe refused`, no Finding. Non-tunnel target
→ 4xx `not tunnel mode`, no Finding.

Target detail tabs **Hardening** | **Router**. NAV six. Honest: no live
UPnP, no live WAN scan, no model-tailored steps, no preview, no LAN
ghosts, no Pulumi, no Azure, no U1.

`PART-U1-NAMED-PARTNER` stays uncovered; `named-partner.md` absent.
Everyday `conformance` stays phase 5; `conformance-7` is the phase gate
and excludes t2/t3:
`python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3`.
No invented token env. No Playwright. `P7-ROUTER-DEMO` named.

### The honest state of this host

T1. Inject actually driven this session:

- `wan_probe=` wrap on `monitor.router_views.probe_nothing_forwarded`
  (HTTP) and the same inject on
  `monitor.router_advisor.probe_nothing_forwarded` (direct). Default
  `wan_probe` is refuse-closed. No live UPnP. No live WAN scan.

NAV is still six.

### Still outstanding — named, not greened

- `PART-U1-NAMED-PARTNER` stays uncovered. `conformance/demos/named-partner.md`
  is absent. This record does not claim a named committed partner.
- Preview environments (private repos), LAN discovery ghosts,
  Pulumi/managed-DB/LB, Azure adapter, overwrite-live restore are later
  Phase 7 polish, not this wave.
- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2
  --exclude-tier t3`. `conformance-7` is not a `review-round` or
  `nightly-gates` prereq.

This record **does not claim** live UPnP, a live WAN scan, model-tailored
steps, preview, LAN ghosts, Pulumi, Azure, or U1.

### Acceptance transcription — real nodeids

`tests/acceptance/test_phase_7.py` (`@pytest.mark.acceptance(phase=7)`),
each body calls the Task 1 proof:

- `test_tunnel_nothing_forwarded_files_and_resolves`
- `test_router_advice_target_tab`

## Phase 7.2 — LAN ghosts (P7-LAN-GHOST-DEMO)

**Date:** 2026-08-26 · **Branch:** `master` · **Recorded by:** Phase 7.2
Task 2. **T1 inject only.** Injected `lan_scan` — not a live nmap run,
not mDNS, not ARP. This session did not run live discovery. No
Playwright.

### What the milestone asked (design note §4)

Zone + enrolled target `web-1`, injected `lan_scan` returning `web-1`
and `printer.lan` → snapshot has one ghost `ghost:printer.lan` and no
`ghost:web-1`. `lan_scan=None` → no ghost kinds. Map list/SVG show
`◌ ghost` + `printer.lan`. Enrolled host skipped. Missing inject adds
no ghosts. Module names no live scanner.

Honest: no live nmap, no preview, no Azure, no U1. LAN ghosts are
done this wave. Preview environments, Pulumi/managed-DB/LB, Azure
adapter stay later.

`PART-U1-NAMED-PARTNER` stays uncovered; `named-partner.md` absent.
Everyday `conformance` stays phase 5; `conformance-7` is the phase gate
and excludes t2/t3:
`python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3`.
No invented token env. No Playwright. `P7-LAN-GHOST-DEMO` named.

### The honest state of this host

T1. Inject actually driven this session:

- `lan_scan=` wrap on `monitor.map_graph.attach_lan_ghosts` (GET map)
  and the same inject on `monitor.lan_ghosts.attach_lan_ghosts`
  (direct). Default `lan_scan` is refuse-closed. No live nmap.

NAV is still six.

### Still outstanding — named, not greened

- `PART-U1-NAMED-PARTNER` stays uncovered. `conformance/demos/named-partner.md`
  is absent. This record does not claim a named committed partner.
- Preview environments (private repos), Pulumi/managed-DB/LB, Azure
  adapter, overwrite-live restore are later Phase 7 polish. LAN ghosts
  are done.
- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2
  --exclude-tier t3`. `conformance-7` is not a `review-round` or
  `nightly-gates` prereq.

This record **does not claim** live nmap, preview, Pulumi, Azure, or U1.

### Acceptance transcription — real nodeids

`tests/acceptance/test_phase_7.py` (`@pytest.mark.acceptance(phase=7)`),
each body calls the Task 1 proof:

- `test_lan_ghosts_inject_skips_enrolled`
- `test_lan_ghosts_map_view`

## Phase 7.3 — Preview (P7-PREVIEW-DEMO)

**Date:** 2026-08-26 · **Branch:** `master` · **Recorded by:** Phase 7.3
Task 2. **T1 inject only.** Injected `visibility` — not a live GitHub
visibility API, not a webhook, not an auto-deploy. This session did not
call live GitHub. No Playwright.

### What the milestone asked (design note §4)

Git Project + Site, injected `visibility="private"`, T2 confirm parent
name, ref `feature/pr-12` → 201, new Site `mesh_only`
`preview-…-feature-pr-12`, `preview_of` set, no Deployment created.
`visibility="public"` → 4xx `public repo refused`. Missing inject → 4xx
`visibility refused`. Wrong confirm → 4xx.

Honest: no live GitHub, no webhook, no auto-deploy, no U1. Preview
environments (private repos) are done this wave. Pulumi/managed-DB/LB
parked (D-134). Azure adapter parked (D-135).

`PART-U1-NAMED-PARTNER` stays uncovered; `named-partner.md` absent.
Everyday `conformance` stays phase 5; `conformance-7` is the phase gate
and excludes t2/t3:
`python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3`.
No invented token env. No Playwright. `P7-PREVIEW-DEMO` named.

### The honest state of this host

T1. Inject actually driven this session:

- `visibility=` wrap on `deploys.preview_views.create_preview` (HTTP)
  and the same inject on `deploys.preview.create_preview` (direct).
  Default `visibility` is refuse-closed (`None`). No live GitHub. No
  webhook. No auto-deploy.

NAV is still six.

### Still outstanding — named, not greened

- `PART-U1-NAMED-PARTNER` stays uncovered. `conformance/demos/named-partner.md`
  is absent. This record does not claim a named committed partner.
- HMAC, live AWS, overwrite-live restore, ScalePolicy/auto stay later
  Phase 7 polish. Preview, LAN ghosts, router advisor, and restore are
  done. Pulumi/managed-DB/LB (D-134) and Azure adapter (D-135) stay
  parked.
- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2
  --exclude-tier t3`. `conformance-7` is not a `review-round` or
  `nightly-gates` prereq.

This record **does not claim** live GitHub, a webhook, auto-deploy,
Pulumi, Azure, or U1.

### Acceptance transcription — real nodeids

`tests/acceptance/test_phase_7.py` (`@pytest.mark.acceptance(phase=7)`),
each body calls the Task 1 proof:

- `test_preview_private_only_creates_sibling`
- `test_preview_t2_http`

## Phase 7.4 — Hub-central DNS-01 (P7-DNS01-DEMO)

**Date:** 2026-08-26 · **Branch:** `master` · **Recorded by:** Phase 7.4
Task 2. **T1 inject only.** Injected `dns01` — not live Let's Encrypt,
not a Caddy ACME DNS block, not a token on a target. This session did
not run live Let's Encrypt. No Playwright.

### What the milestone asked (design note §4)

Unproxied public Site + injected `dns01` → `ensure_site_certificate`
issues, upserts TXT `_acme-challenge`, pushes PEM, `mode` `hub_dns01`,
`unproxied-cert:{pk}` RESOLVED. Missing inject refuses with Finding
`unproxied-cert` + `Dns01Error`. Beat `renew_due` /
`hub-dns01-renew-daily` reissues due `hub_dns01` rows.

Honest: **no live Let's Encrypt**, no invented token env, no Caddy
DNS-01, no U1. Hub-central DNS-01 T1 Fake landed this wave. Pulumi /
managed-DB/LB parked (D-134). Azure adapter parked (D-135).

`PART-U1-NAMED-PARTNER` stays uncovered; `named-partner.md` absent.
Everyday `conformance` stays phase 5; `conformance-7` is the phase gate
and excludes t2/t3:
`python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3`.
No invented token env. No Playwright. `P7-DNS01-DEMO` named. NAV six.

### The honest state of this host

T1. Inject actually driven this session:

- `dns01=` wrap on `deploys.certs.ensure_site_certificate` /
  `deploys.dns01.issue_unproxied`. Default `dns01` is refuse-closed
  (`None`). Injected `dns01` upserts TXT `_acme-challenge` via
  `desired["dns"]` and returns PEM. No live Let's Encrypt. No token
  on the target.

NAV is still six.

### Still outstanding — named, not greened

- `PART-U1-NAMED-PARTNER` stays uncovered. `conformance/demos/named-partner.md`
  is absent. This record does not claim a named committed partner.
- Live Let's Encrypt / inventing a test-zone token, HMAC, overwrite-live
  restore stay later. Preview, LAN ghosts, router advisor, and restore
  are done. Pulumi/managed-DB/LB (D-134) and Azure adapter (D-135) stay
  parked.
- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2
  --exclude-tier t3`. `conformance-7` is not a `review-round` or
  `nightly-gates` prereq.

This record **does not claim** live Let's Encrypt, a Caddy ACME DNS
block, Pulumi, Azure, or U1.

### Acceptance transcription — real nodeids

`tests/acceptance/test_phase_7.py` (`@pytest.mark.acceptance(phase=7)`),
each body calls the Task 1 proof:

- `test_unproxied_dns01_issues_and_refuses`
- `test_dns01_renew_beat_and_surfaces`
