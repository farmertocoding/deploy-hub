# Phase 4 Design Note — Security suite

**Phase:** 4 per §I (addendum 2026-07-30) · gate float **`4`**
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-23 · **Seat:** Grok 4.6
**Revision:** r2 — design panel MERGE-AFTER-FIXES (Architect + QE; Security MERGE). Required fixes: KMS port under `providers/`; Task 1 owns every `CheckRun.Kind` + `shipped_at`; pin `HUB_VAULT_KMS_KEY_ID`; backup blob is Hub-local path; Task 0 names d017/d023 rewrites; drop dangling D-067. §7 is binding.
**Estimate:** 1–2 wk incl. review. Protective cut: **D-054**. Phases 0–3b MUST + leftover honesty wave are on `master` @ `21d18a6`. Leftover Task 8 (LE-staging) stays blocked (`HUB_TEST_CF_TOKEN` unset). **Do not invent `HUB_TEST_CF_TOKEN`. `HUB_TEST_DNS_ZONE` stays retired.**
**Branch:** these two docs land on **`p4-design`**; Implementers cut task branches from it. Never implement on `master`. Sensitive-path merges go through the recorded panel vote.
**Closed schema wave:** `0009_phase3.py` and `0010_phase3b.py` stay closed. Phase 4 adds **one** migration, `0011_phase4.py`, on **`DnsZone` + `AuditEvent` only** — denormalized `DnsZone.provider` + unique `(provider, name)`; `AuditEvent.prev_hash` and nullable `AuditEvent.shipped_at`. No new Hub tables. **Task 1 is the only Hub `core/models.py` writer this phase:** it also adds Python-only `CheckRun.Kind` values `ssh_rotate`, `backup`, `attack_playbook`, `tailscale_devices` and the BACKUP closed `clean()` key set. Later tasks do not edit `core/models.py`. Backup ciphertext lives on a Hub-local path (see C7); `CheckRun.results` holds metadata only. Do not add a Site FK to `CheckRun`. Do not add `Site.tier`. django-otp-webauthn’s own migrations are third-party and allowed beside `0011`, not a second Hub schema wave.
**Panel:** §7 is binding. An Implementer who invents a path, env, Finding fingerprint, or gate shape that §7 does not name is implementing the wrong design.

## 1. What lands this phase

Phase 3b finished the operator path that makes a public site deployable. Phase 4 is the security suite: hardware step-up, scanner-trust re-landed behind a written threat model, edge auto-response, topology findings, scheduled SSH rotation, and a backup operator surface. §6 A/B/C already exist (scanner, catalog hardening, cert/uptime/traffic). This phase does **not** rebuild them.

### 1.0 D-012 threat model (page 1 — write this before any scanner re-wire)

Joseph: threat model first. Specs already exist (`docs/spec-declared-test-material.md`, `docs/spec-r7-enforce-declaration-acceptance.md`). `scanner/declarations.py` and parked tests already on the tree. **Do not rewrite the parser.** The six adversarial axes already encoded in that module are the floor, not the ceiling:

1. **Forged report lines** — `reason`/`path` are repo-controlled and printed into the report. Newlines in a reason forge section headers. Rule: refuse, never repair.
2. **Unicode line separators** — U+2028 / U+2029 / U+0085 break `str.splitlines` and JS LineTerminators. C1 is refused here, not left to PyYAML’s printable set.
3. **In-line label / bidi forgery** — bidi overrides and zero-width code points make a reason unreviewable. Ordinary non-ASCII (this fleet is Taiwanese) stays accepted.
4. **Settings-package / manifest-guard** — declaring the scan root or a path holding files the scanner keys on is a warning with no downgrade.
5. **Parser resource limits** — a malformed `deployhub.yaml` warns and applies nothing; it does not crash the scan.
6. **Content-keyed confirm id (D-012r2)** — `confirm_question_id(path, reason)` is sha256(path + "\n" + reason)[:16]; the index is gone from the key. Reason-swap and index-round-trip stay closed by construction.

Plus the two rulings the re-land must not lose:

- **D-012r / R7-1:** a declaration is a *request*. No acceptance, no downgrade. `[proof]` axis, `.env` handler, and undeclared heuristic lines stay blocking. `blocking_only_declared: false` is unconditional.
- **D-012r2:** editing path or reason yields an id nobody has answered; `missing_required` re-blocks. `wizard.service.scrub_orphaned_declaration_answers` returns as hygiene, never the boundary.

**Trust statement.** A scanned repo may *request* that heuristic-axis `core.secret-scan` findings under a named tree stop blocking. The repo is not a principal. The operator is. Scan-time tier drop from a file the repo writes is unilateral self-exemption (D-012r). That is the attack, not a feature.

**Attacks that must have E2E on re-land (parser-only is not enough):** repo self-downgrade · reason-swap · index round-trip · scan-root swallow · proof-axis bypass. Invert `tests/test_d012_out_of_phase_1.py::test_d012_no_live_code_imports_the_parked_declarations_module` and `::test_d012_a_live_run_never_loads_the_parked_module`. Parked parser tests keep running; they do **not** carry the full-text `SCAN-DECLARED-*` markers after Task 0 (D-055 SCAN-M4). Task 0 rewrites `tests/test_d017_declared_reqs_not_phase_2.py` so it no longer requires those markers on the parser file.

Re-land work is wiring, not invention: `scanner/core.py::scan` loads the file once and extends questions via `declarations.confirm_questions`; `scanner/modules/fallbacks.py::_check_secret_scan` consults `covers`/`label` for the heuristic axis only and **does not drop tier at scan time**; `wizard/questions.py::missing_required` takes declaration confirm ids from the project’s scan report (content-keyed); `wizard/service.py` restores `scrub_orphaned_declaration_answers`.

### 1.1 MUST

1. **WebAuthn primary + TOTP fallback + second (phone) passkey + T1 `require_recent_touch` + idle timeout.** `core/otp.py` grows WebAuthn enroll/confirm beside TOTP (`django-otp-webauthn`). Login accepts WebAuthn assertion *or* TOTP *or* recovery code. Onboarding enrolls a **platform passkey on the phone** as the second WebAuthn credential (§F5). `core/permissions.py` is new: `RequireRecentTouch(minutes=5)` reads `request.session["hardware_touch_at"]` written **only** by a WebAuthn assertion on `POST /api/auth/webauthn/touch/` (Security F1). TOTP and recovery codes authenticate login, never T1. Two WebAuthn credentials before T1 is available; TOTP-only operators keep today’s T1 refuse. T1 ids: existing `target.delete`, `key.export`, `kek.rotate`, **plus `ssh.rotate`**. Hardware touch **plus type-the-name**. T3 (`site.rollback`, `site.restart`, `check.rerun`) stay ungated. `site.auto_mode` stays T2. Global `reconcile.kill_switch` (if the kill-switch control lands) is T1, not auto-mode. `frontend/src/actions.js` `presentation()`: T1 `stepUp: "required"`; T3 `stepUp: "none"`; standing pin that rollback never grows step-up chrome. `core/middleware.py` grows `IdleTimeoutMiddleware` enforcing existing `HUB_SESSION_IDLE_TIMEOUT`. Enrollment prefixes gain `/api/auth/webauthn/` under the existing `/api/auth/` prefix. `?sim=` mounts the Shell (extract Login/Enroll). T4 Playwright is **SLIP** (not in the tree; do not extend `VALID_TIERS`). T1 protocol tests MUST exist either way. Registry: `SEC-A2-WEBAUTHN-PHASE4`, `SEC-F5-T1-HARDWARE-TOUCH`. Retire `UX-F5-ACTION-TIERS` waiver when the hardware clause is marked.

2. **D-012 re-land** after §1.0 and after Task 0’s SCAN-M4 split. Do not rebuild the scanner or wizard. Do not guess test material from directory names.

3. **Attack playbook L5.** `monitor/attack_detector.py` z-scores existing `TrafficStat` minute rows. `monitor/attack_playbook.py` engages: `set_security_level(under_attack)` → `ban_ip` → notify via existing pager → auto-relax. Construction: `providers/registry.py::edge_protection_for(zone)` loads `DnsAccount.edge_token_ref` and returns `CloudflareEdge` (new class **in** `providers/cloudflare.py`, same HTTP helper, Bearer-only, same one-zone probe). Playbook takes `EdgeProtection | None` and degrades to notify-only in code (§D5) — never a silent no-op. Alert kind `attack-playbook-engaged` already exists. Visible Sites `AttackState` (CertState twin) + Home banner; pager `click_url` is `{HUB_PUBLIC_URL}/#/findings/{id}` (hash-only SPA). `scaling/attack_gate.py::refuse_if_attack(site)` is a named refuse: attack-shaped load **never** scales (scaler is Phase 6; the gate must still exist). Never a second CF client. `deploys/` never imports `providers/cloudflare`. Token values never in Findings, CheckRun, logs, or task args.

4. **Topology advisor r1–r5 as Findings** (D-041: not a new graph library). `monitor/topology.py` reads `monitor/map_graph.py::graph_snapshot()` plus Site/Target/SiteInstance and files Findings. Optional chips on the existing SVG that link `#/findings/<id>`. r6–r8 stay later. Advisors remain tabs, not a 7th NAV item.

5. **Scheduled quarterly SSH rotation (B7 now-step).** Dual-key overlap: generate new Ed25519 in-Hub → append pubkey → `Transport.probe` login with the new key → only then drop the old pubkey → point `Target.ssh_key_ref` → probe old fails / new works → revoke old Secret. Never `ssh-keygen` on the target. Never clobber `authorized_keys` with a single-key install during overlap. `ssh.rotate` is T1. Beat `ssh-rotate-quarterly` (90 d). New alert kinds (register before `raise_alert`): `ssh-rotation-incomplete` P1, `ssh-rotation-stale-key` P2. Also file `ssh-host-key-mismatch` as a Finding from `SshTransport` (today it is AuditEvent-only). SSH-CA stays Phase 5 / §J. Run-twice: second pass zero mutating Transport calls (D-018).

6. **Backup operator surface (E5) with a real store.** Persist sealed dumps on a **Hub-local path** `/var/lib/deploy-hub/backups/{checkrun_pk}` (mode 0600, never in git). `CheckRun.Kind.BACKUP` closed results `{schema_version, unit_id, site_id, bytes, digest, stored_at}` where `bytes` is **integer size** and `digest` is sha256 of the sealed blob. The list API returns metadata only — no ciphertext, no key. Beat `backup-nightly`. On collect/seal/store failure **and** a missing nightly dump for a registered unit: `raise_alert("hub-db-or-backup-failure")` P1 (kind exists, never filed today) plus existing `audit("backup-failed")`. Operator: Sites-detail list + T2 “test backup now” + §6.6 restore **command block** (no Restore POST / button). Fill monthly restore-to-clean-container drill body; SKIPPED only when no BackupUnit exists. Restore *UI* stays Phase 7. Do not claim 24 h Hub-down. Sealed dump uses `Secret.Kind.BACKUP_KEY`, never the KEK.

7. **Leftover honesty.**
   - Retire D-045 `alerts` alias.
   - DnsZone `(provider, name)` DB unique — Task 1.
   - `SEC-B4-REDIS-CROWN-JEWEL`: parse `docker-compose.yml` + JSON serializers. Convert `verify: checklist` → `test`. Retire the waiver.
   - `SEC-69-NO-SECRETS-IN-EXHAUST`: gate over captured pytest stdout/stderr/log and Celery task kwargs. Convert to `verify: test`. `make log-scrub` stays the source-scan it is.

8. **Tailscale device-list poll.** `providers/tailscale.py` + `FakeTailscale`. Beat `tailscale-device-audit-daily`. Absent vault ref → skip-only + dated waiver (D-043 shape). **Do not invent a live token env.** Settings ref `HUB_TAILSCALE_API_TOKEN_REF` (vault owner-id, default `""`). Tailnet-lock **enablement** is SLIP (evaluate + written decision, not default-on).

9. **KMS KEK rung ③ adapter, T1 only, plus DEK cache.** The AWS KMS **client** lives in `providers/kms.py` (D4: `vault/` and `tests/` must not import `boto3`/`botocore`). `vault/kek.py::KmsKEK` takes that port and never imports boto3. `get_backend()` accepts `VAULT_KEK_BACKEND=kms` (from existing env `HUB_VAULT_KEK_BACKEND`) and **refuses unless `VAULT_KMS_KEY_ID` is set**. Pin: env `HUB_VAULT_KMS_KEY_ID` → setting `VAULT_KMS_KEY_ID` default `""`. Tests use moto 5.x `@mock_aws` in the **provider** module (**not LocalStack**); `tests/test_kms_kek.py` must not import boto3. Keyfile stays the test/dev rung and still does **not** defeat a stolen Hub disk. `vault/service.py` caches unwrapped DEKs in process memory (keyed by secret pk + kek_id; never log/serialize); unwrap on miss only. A KMS blip must not fail every `get` and must not take down serving sites. `rewrap` is the ①→③ path (already written). **Live AWS KMS is a Joseph interrupt.** Prod settings must not default to `kms` in this wave. Any live S3 adapter, if Joseph-approved later, also lives under `providers/` — T1 fake shipper in `core/` has no SDK.

10. **Audit hash chain (local MUST).** `audit()` writes `prev_hash` and **never blocks on S3**. T1 fake shipper + skip-unless-bucket may land in the same wave; live Object Lock is a Joseph interrupt. `detail` may hold refs/fingerprints, never DEKs, tokens, recovery codes, PEM. S3 down → P2 `audit-ship-failed` (do not overload `hub-db-or-backup-failure`).

### 1.2 MUST vs later

| Item | Line |
|---|---|
| WebAuthn + phone passkey + `require_recent_touch` T1 (WebAuthn-only writer) + idle timeout + sim Shell | **MUST** |
| D-012 threat model + SCAN-M4 Task 0 + live-path re-land | **MUST** |
| Attack playbook L5 + never-scale named refuse + Sites/Home visible state | **MUST** (T1 fakes) |
| Topology r1–r5 as Findings | **MUST** |
| Quarterly SSH rotation, dual-key, T1 | **MUST** (T1 fakes) |
| Backup persist + Beat + P1 + list + test-now + command block + restore-drill body | **MUST** |
| D-045 retire, DnsZone unique, SEC-B4 parse, SEC-69 exhaust | **MUST** |
| Tailscale API seam + skip-unless device poll | **MUST** |
| `KmsKEK` T1 + DEK cache + refuse-unless-configured | **MUST** (no live AWS) |
| `AuditEvent.prev_hash` hash chain | **MUST** (local) |
| Hub-central DNS-01 (`TLS-B2-HUB-DNS01-UNPROXIED`) | **named first slip.** Task 0 dated waiver so `conformance-4` can start. Unproxied refusal stays. Do not mark full-text `SEC-B2`. |
| T4 Playwright | **SLIP.** Do not extend `VALID_TIERS`. |
| Audit off-host S3 Object Lock live shipper | **SLIP** — T1 fake + skip-unless-bucket |
| Live AWS KMS | **Joseph interrupt / not this wave** |
| YubiKey KEK rung ② | **SLIP** |
| Tailnet lock enablement | **SLIP** |
| Session↔device binding enablement | **SLIP** |
| `TIME_ZONE` operator-local | **SLIP** — already UTC |
| App-log / jobs UI | **OUT** (3b-later) |
| LE-staging credentialed run, 24 h Hub-down | **OUT** |
| Partner intake, AWS/Azure, SSH-CA, Router Advisor, restore UI | **OUT** |

## 2. Interfaces / tables that change

**Migration `0011_phase4.py` (DnsZone + AuditEvent only) — Task 1 owns this file and `core/models.py` for the whole phase:**
- `DnsZone.provider` CharField. `save()` / `full_clean()` copy `account.provider`. `UniqueConstraint(fields=["provider", "name"], name="uniq_dnszone_provider_name")`. Keep `uniq_dnszone_account_name`. `clean()` stays defense-in-depth.
- `AuditEvent.prev_hash` CharField(max_length=64, blank=True, default=""). `audit()` writes `prev_hash = sha256((prev_hash + canonical_row).encode("utf-8")).hexdigest()` where `canonical_row` is the JSON of `{ts, actor_id, source, action, object_type, object_id, detail, source_ip, severity}` with sorted keys and no whitespace. Genesis `prev_hash=""`. Never blocks on S3.
- `AuditEvent.shipped_at` DateTimeField(null=True, blank=True) — nullable now so Task 11 cannot open a second Hub wave.
- Python-only `CheckRun.Kind`: `SSH_ROTATE = "ssh_rotate"`, `BACKUP = "backup"`, `ATTACK_PLAYBOOK = "attack_playbook"`, `TAILSCALE_DEVICES = "tailscale_devices"`. BACKUP `clean()` requires results keys exactly `{schema_version, unit_id, site_id, bytes, digest, stored_at}`. Later tasks do **not** edit `core/models.py`.

No new Hub models. WebAuthn device tables come from `django-otp-webauthn`’s migrations. Adopt results closed schema unchanged.

**ACTION_TIERS additions:** `ssh.rotate` T1. Optional `reconcile.kill_switch` T1. Do not move `site.auto_mode` to T1.

**Interfaces:** see §7. Pager deep links use the hash router. Backup lives on Sites detail, not a 7th NAV item. Security credentials live on a Settings tab, not NAV.

**Gates:** `make conformance-4` = `python conformance/check.py --phase 4 --exclude-tier t2 --exclude-tier t3`. `make review-round` uses that via the `conformance` target (phase bump 3 → 4). `conformance-3` remains **all-tiers Phase 3** (nightly). Do **not** claim `conformance-3` excludes live tiers. Do **not** add an all-tiers 4 gate. Do **not** add `t4` to `VALID_TIERS` this phase.

## 3. Applicable registry reqs

**Already due at phase 4:** `SCAN-DECLARED-TEST-MATERIAL` · `SCAN-DECLARED-GUARDS` · `SEC-A2-WEBAUTHN-PHASE4` · `SEC-F5-T1-HARDWARE-TOUCH` · `TLS-B2-HUB-DNS01-UNPROXIED` (first slip — Task 0 waiver; unproxied refusal stays).

**Task 0 SCAN-M4 (QE F1, load-bearing):** parked parser tests in `tests/test_scanner_declarations.py` must **not** keep the full-text `SCAN-DECLARED-*` markers when `--phase 4` becomes due. Either a new parser-scoped id `SCAN-DECLARED-PARSER` carries those markers, or the markers are stripped (tests keep running unmarked). Full-text ids stay phase 4, **unmarked**, uncovered until the live path has marked E2E. Clause-scoped `WAIVERS.md` line until re-land.

**New (Task 0), tier-less (no `tier:` key):**
- `SEC-L5-ATTACK-PLAYBOOK`
- `SEC-L5-NEVER-SCALE-ATTACK`
- `TOPO-R1-R5-FINDINGS`
- `SEC-B7-SSH-QUARTERLY-ROTATE`
- `UX-E5-BACKUP-OPERATOR`
- `SEC-B8-TAILSCALE-DEVICE-POLL`
- `SEC-A3-KMS-KEK-ADAPTER`
- `SEC-B3-AUDIT-HASH-CHAIN`
- `P4-SECURITY-DEMO` (`verify: demo`, `demo: conformance/demos/phase-4.md`)

**Waivers this phase acts on:**
- Task 0: `WAIVED: TLS-B2-HUB-DNS01-UNPROXIED` — first slip, unproxied refusal remains (QE F3).
- Task 0: SCAN-DECLARED full-text clause waiver until live-path E2E.
- Retire `UX-F5-ACTION-TIERS` when `SEC-F5-T1-HARDWARE-TOUCH` is marked.
- Retire `SEC-B4-REDIS-CROWN-JEWEL` and `SEC-69-NO-SECRETS-IN-EXHAUST` when their tests are marked.
- Do **not** retire `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`, `HARNESS-T3-LE-STAGING`, `DNS-CF-T3-LIVE`, or `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven`.
- New skip-unless-configured waiver for Tailscale poll if no vault ref.

## 4. Exit demo

Enroll WebAuthn security key + phone platform passkey → TOTP remains fallback → T1 `target.delete` / `ssh.rotate` refuse without recent **WebAuthn** touch and without type-the-name; after touch+name they run and audit → TOTP-only session: T1 still refused with “add a passkey” → T3 rollback is one click and never step-up gated → idle timeout kills a stolen session past 30 min → a repo with `deployhub.yaml` drill tree: heuristic lines labelled and still blocking until wizard accept; `[proof]` / `.env` still block; root declaration refused; reason-edit invalidates confirm id → TrafficStat z-score trip engages playbook through `edge_protection_for` (FakeEdgeProtection in T1): Under-Attack set, IP banned, P1 Finding + Sites AttackState + Home banner, auto-relax; `refuse_if_attack` returns the named refuse; missing edge ref is notify-only not silent → map Findings for r1–r5 → quarterly SSH rotate run-twice with dual-key overlap (second run zero mutating Transport calls) → BackupUnit list on Sites + test-now seals a dump with the backup key, not the KEK; restore command block visible, no restore POST; failed dump files P1 `hub-db-or-backup-failure` → `alerts` topic unauthorized → compose parse proves Redis unpublished + requirepass + JSON serializers → exhaust gate greps captured output → Tailscale poll skip-only (no token) with dated waiver **or** FakeTailscale unknown-device Finding → `KmsKEK` wrap/unwrap under moto; unconfigured `kms` refuses; DEK cache survives a fake KMS blip; keyfile still boots tests.

Record: `conformance/demos/phase-4.md`. `make review-round` twice clean (Phase 4 minus live tiers). `make conformance-4` is the phase gate and **excludes t2/t3**. `conformance-3` remains the all-tiers Phase 3 nightly gate. Live CF / KMS / S3 stay skipped-only + dated waiver, never a T1-sibling green. No 24 h Hub-down. No invented test-zone token. No paid AWS.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

Not open `DECISION:` blockers. Irreversible/spend: live AWS KMS and live S3 Object Lock are Joseph interrupts. MUST does not enable them.

- **D-054** Protective cut — §1.2.
- **D-055** D-012 re-land is threat-model (§1.0) + SCAN-M4 at Task 0 + re-wire of `scanner/core.py`, `fallbacks._check_secret_scan`, and wizard acceptance. Do not rewrite `scanner/declarations.py`. Invert the two “no live import” tests. Parser tests do not prove the full text.
- **D-056** One schema wave: `0011_phase4.py` = `DnsZone.provider` + unique `(provider, name)` + `AuditEvent.prev_hash` + nullable `shipped_at`. Task 1 is the only `core/models.py` writer and also adds the four Python-only CheckRun kinds plus the BACKUP closed key set. No new Hub tables. django-otp-webauthn migrations are third-party.
- **D-057** `edge_protection_for(zone)` is the only EdgeProtection constructor; `CloudflareEdge` lives in `providers/cloudflare.py` and loads `edge_token_ref`. Playbook degrades to notify-only when None. Attack-shaped load never scales (`scaling/attack_gate.py`). DNS client never loads `edge_token_ref`; edge client never loads `dns_token_ref`.
- **D-058** Tailscale device-list poll is T1 Fake + skip-unless-configured. Tailnet-lock enablement is a written evaluation, not default-on. Session↔device binding is the same shape (§J5).
- **D-059** AWS KMS client lives in `providers/kms.py`. `KmsKEK` takes that port and never imports boto3. Env `HUB_VAULT_KMS_KEY_ID` → `VAULT_KMS_KEY_ID` default `""`; `VAULT_KEK_BACKEND=kms` with empty key id refuses. T1 moto on the provider module. In-process DEK cache. Keyfile remains test/dev and does not defeat a stolen Hub disk. Live AWS KMS is a Joseph interrupt (~$1/mo). YubiKey rung ② may slip.
- **D-060** `conformance-4` / review-round = `--phase 4 --exclude-tier t2 --exclude-tier t3`. `conformance-3` stays all-tiers Phase 3. Do not claim it excludes live tiers. Do not add an all-tiers 4 gate. Do not extend `VALID_TIERS` with `t4`. T4 Playwright is SLIP; T1 WebAuthn protocol tests are MUST. Task 0 waives `TLS-B2-HUB-DNS01-UNPROXIED` so the gate can start.
- **D-061** Leftover honesty: retire D-045 alias; DnsZone unique in `0011`; SEC-B4 compose parse; SEC-69 exhaust gate. `TIME_ZONE` stays UTC (SLIP operator-local).
- **D-062** T1 step-up is WebAuthn hardware touch writing `hardware_touch_at`; TOTP/recovery never write it. T3 never takes `RequireRecentTouch`. `ssh.rotate` is T1. `site.auto_mode` stays T2. Two passkeys before T1 is available.
- **D-063** Backup MUST includes persist + Beat + P1 `hub-db-or-backup-failure` + Sites list + test-now + restore command block + restore-drill body. Restore UI stays Phase 7.
- **D-064** SSH rotate is dual-key overlap, probe-before-revoke, T1, run-twice zero mutating calls. Incomplete rotation is P1; stale-old-key after intended revoke is P2.

## 6. Out of scope (explicitly)

App-log viewer · scheduled-jobs UI + `jobs_image` · Hub-central DNS-01 (named first slip; refusal stays) · restore UI · LE-staging credentialed run · 24 h Hub-down · live AWS KMS · live S3 Object Lock (unless Joseph) · YubiKey KEK ② · tailnet-lock enablement · session↔device binding enablement · SSH-CA · AWS/Azure · partner intake · Router Advisor · scaler implementation (the refuse gate is in) · rebuilding scanner/wizard/adopt · inventing `HUB_TEST_CF_TOKEN` · restoring `HUB_TEST_DNS_ZONE` · a 7th NAV item · Playwright as a review-round prerequisite.

**May slip without failing the MUST demo:** DNS-01 (first) · T4 Playwright · fake S3 audit shipper completeness beyond hash chain · YubiKey ② · tailnet-lock writeup · Topology r3 live docker-network inspect on T2 (T1 protocol test is enough). **Not** slip-able: WebAuthn + T1 touch + T3 ungated + idle timeout, D-012 SCAN-M4 + re-wire, L5 playbook on FakeEdgeProtection, never-scale refuse, topology r1–r5 Findings, SSH rotate playbook, backup persist/Beat/P1/list, D-045 retire, DnsZone unique, SEC-B4, SEC-69, `0011`, KmsKEK refuse-unless-configured + DEK cache, Tailscale skip-unless poll.

## 7. Closed answers (panel — do not reopen)

### C1 — D-012 re-land

Do not rewrite `scanner/declarations.py`. Do not guess from directory names. Task 0 SCAN-M4-splits full-text markers **before** `--phase 4` is due. Invert the two no-import tests on the re-land task. Wizard confirms are content-keyed; unanswered refuses materialize. `[proof]` / `.env` / undeclared heuristic never clear on acceptance. E2E the five attacks against a real preflight/materialize, not parser-only.

### C2 — T1 vs T3

T1 = `target.delete`, `key.export`, `kek.rotate`, `ssh.rotate` (and `reconcile.kill_switch` if that control lands). T3 never takes `RequireRecentTouch`. Named tests: `test_rollback_is_one_click_and_never_step_up_gated` stays green; `test_t1_target_delete_refuses_without_recent_touch`; `test_t1_requires_type_the_name`; `test_t1_totp_does_not_write_hardware_touch_at`; `test_t1_refused_until_two_webauthn_credentials`. Auto-mode remains T2.

### C3 — EdgeProtection construction

`edge_protection_for(zone)` only. Same fail-closed as `dns_provider_for`. Absent edge ref → `None` → notify-only Finding + degraded Sites line, never a silent no-op. Fingerprint `{kind}:{entity}` = `attack-playbook-engaged:{zone.pk}`. Pager URL is hash-routed.

### C4 — Never-scale

`scaling/attack_gate.py::refuse_if_attack(site)` raises a named exception / returns a Finding when playbook is engaged for that site’s zone. Phase 6 must call it; Phase 4 tests the refuse. No scaler loop.

### C5 — Topology fingerprints

- `topology-hub-isolation:hub`
- `topology-blast-radius:{target_pk}`
- `topology-site-network:{site_pk}`
- `topology-db-mesh-only:{site_pk}`
- `topology-lan-segment:{zone_pk}`

Copy follows §6.6. Accept-risk requires a reason. No graph library.

### C6 — Env names

Do not invent `HUB_TEST_CF_TOKEN`. Do not restore `HUB_TEST_DNS_ZONE`.
- Tailscale: `HUB_TAILSCALE_API_TOKEN_REF` (vault owner-id, default `""` → skip).
- KMS: existing `HUB_VAULT_KEK_BACKEND` → `VAULT_KEK_BACKEND`. New: `HUB_VAULT_KMS_KEY_ID` → `VAULT_KMS_KEY_ID` default `""`. Refuse `kms` when key id is missing. Tests use moto in `providers/kms.py`. `vault/` and `tests/` do not import boto3.
- Audit ship (SLIP): skip unless bucket configured.

### C7 — Backup

Sealed blob path = `/var/lib/deploy-hub/backups/{checkrun_pk}` (0600). `bytes` is integer size; `digest` is sha256 hex of the sealed file. List/test-now hide key material and ciphertext. Persist + Beat + P1. List + test-now on **Sites detail**. Restore command block is text. No `POST .../restore/`. No FileField, no new table, no Site FK. Fingerprint for backup failure is existing `hub-db-or-backup-failure`. Restore-drill SKIPPED only when siteless.

### C8 — SSH rotate

Dual-key overlap. `Transport.probe` for inspect. Incomplete = P1 `ssh-rotation-incomplete`. Stale-old after revoke-intended = P2 `ssh-rotation-stale-key`. Overlap itself is not a Finding. Also `raise_alert("ssh-host-key-mismatch")` from `_refuse`.

### C9 — Exhaust / Redis / UX

SEC-69: captured exhaust, not `make log-scrub`. SEC-B4: compose parse, not an external port-scan. `?sim=` mounts Shell. Login/Enroll extracted so F8 can see them. T1 overlay is in the phone set (390 px). Backup list is not a fourth F6 screen. No 7th NAV item.

### C10 — Schema / gates

`0011` is DnsZone.provider + unique `(provider, name)` + AuditEvent.prev_hash + shipped_at. CheckRun kinds and BACKUP closed keys land in Task 1. `prev_hash = sha256((prev || canonical_row).encode("utf-8")).hexdigest()`. `conformance-4` excludes t2/t3. `conformance-3` all-tiers Phase 3. New phase-4 ids are tier-less. Task 0 waives DNS-01 and SCAN-M4-splits D-012.

### Already correct (keep)

D-054 cut: DNS-01 first slip, app-log/jobs UI out, no 24 h Hub-down, no invented `HUB_TEST_CF_TOKEN`. `0009`/`0010` closed. `HUB_TEST_ZONE_SLUGS` allowlist; `HUB_TEST_DNS_ZONE` retired. `findings` is the canonical topic (`alerts` dies this phase). Triple key for test-plane DNS. `deploys/` never imports `providers.cloudflare`. Secrets through the vault. Reversible-by-default.

### Sensitive-path additions (Task 0 claims before the first line of code)

`core/actions.py` · `core/audit.py` · `core/permissions.py` · `core/webauthn.py` if split out of `otp.py` · `frontend/src/actions.js` · `wizard/materialize.py` · `wizard/service.py` · `scanner/core.py` · `monitor/attack_playbook.py` · `monitor/attack_detector.py` · `monitor/topology.py` · `scaling/attack_gate.py` · `provision/ssh_rotate.py` · `providers/tailscale.py` · audit-shipper module when named. `vault/**` and `providers/**` already listed. Do not broaden to `scanner/**` or `wizard/**` wholesale.
