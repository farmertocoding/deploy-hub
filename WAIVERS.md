# WAIVERS.md — one line per waived finding: fingerprint + reason + date
# (build-process.md §4: a finding is a fix-with-regression-test OR a line here. Nothing else.)

WAIVED: .github/workflows+supply-chain+actions-pinned-by-tag — third-party actions pinned by major tag, not SHA; repo is local-only until D-001 GitHub move (Phase 2.5 at latest), at which point actions get SHA-pinned in the same PR that enables branch protection (2026-08-03)

# R4-9 (SPEC-gate-integrity.md §3.2 rule 4): `verify: checklist` reqs now have to name the
# gate that enforces them. These three have no gate on this tree. Per the spec, a waiver is
# the correct answer where no gate exists yet — inventing one to reach green is not. Each
# names what would retire the waiver. Fingerprint = req id + uncovered(no gate).
WAIVED: SEC-B4-REDIS-CROWN-JEWEL — uncovered(no gate): Redis is compose-internal with requirepass and JSON-pinned Celery serializers in docker-compose.yml today, but nothing asserts it — the compose file is read by no test and the §6B external port-scan of the Hub is a Phase-2 activity. Retire when a test parses docker-compose.yml for {no published redis port, requirepass set, CELERY_*_SERIALIZER == json} and this req becomes verify: test (2026-08-11)
WAIVED: PROC-REGRESSION-TEST — uncovered(no gate): build-process.md §5 puts this on the auto-fix PR template plus "a path-glob check on any PR closing an issue"; neither the template nor the check exists on this tree, and a PR-scoped check cannot run until the repo moves to GitHub (D-001). Retire with the PR-template + path-glob workflow in the D-001 move PR (2026-08-11)
WAIVED: PROC-SENSITIVE-HUMAN-MERGE — uncovered(no gate): the `sensitive-path-guard` job in push-checks.yml is a placeholder that only echoes "wire branch-protection + CODEOWNERS when repo moves to GitHub (D-001)"; naming it in `gate:` would make check.py green on a step that enforces nothing, which is the exact defect R4-9 exists to kill. Retire when CODEOWNERS + branch protection derived from conformance/paths.yaml land with D-001 (2026-08-11)

# Round-5 F1: a gate that enforces *something else* is not this requirement's gate. The
# review found SEC-69-NO-SECRETS-IN-EXHAUST reported `verified` on `make log-scrub`, which
# greps source files for `SECRET_KEY\s*=`; the requirement is about exhaust after write and
# names a CI scrubber over captured test output. `gate: log-scrub` removed from the registry;
# log-scrub itself kept as the source-scan gate it genuinely is.
WAIVED: SEC-69-NO-SECRETS-IN-EXHAUST — uncovered(no gate): the requirement says secrets never appear in logs, Celery task args or frontend responses after write, and that CI greps test output for plaintext markers; nothing on this tree checks any of those three surfaces. `make log-scrub` is a source scan for an assignment literal and enforces materially less, so claiming it as this req's gate reported a green that was not earned. Retire when a gate scans captured test output (pytest stdout/stderr and log capture) and Celery task kwargs for the vault's plaintext markers and this req becomes verify: test (2026-08-11)

# Round-5 F9: an unreachable check, recorded rather than left silent. Fingerprint = the
# artifact tree + why nothing reads it.
# R4-11 WI-3 (audit finding, 2026-08-11): a requirement read `verified` on one clause of
# three. Fingerprint = req id + the unproven clauses. The two markers that produced the
# green were removed rather than left claiming the whole text; the tests they were on
# still run. Retiring this waiver means restoring those markers. See DECISIONS.md D-009.
# Clause (b) retired 2026-08-11 by D-010 / SPEC-django-common-checks.md.
WAIVED: SCAN-M4-EXPOSURE-AUTH — blocker-escalation clause unimplemented: "Blocker when the wizard tags financial/personal data" has no code path — `scanner/modules/fallbacks.py::_check_exposure_auth` returns only ok/warning, and no wizard question anywhere tags data sensitivity (question set unchanged: site.domain, site.exposure, django.{domain,exposure,db,env.*}, node-ts.{service-package,dev-packages,data-dir,worker-threads,exposure,exclusive-upstream}, dockerfile.{domain,exposure,port,env}, static.{domain,exposure}), so there is no answer for an escalation to read. Clause (b) of the 2026-08-11 waiver — django scan reports never carried `core.exposure-auth` — is RETIRED (2026-08-11): `scanner/core.py::scan` now composes the common core suite into every report (D-010, Architect ruling; the gap was the whole seven-check suite, not this check alone). The warning clause now holds for every registered module, proven by tests/test_scanner_fallbacks.py::test_no_auth_indicators_fires_exposure_auth_warning, ::test_auth_indicators_silence_exposure_auth, tests/test_scanner_node_ts.py::test_issue_r4_11_a_node_ts_scan_surfaces_the_exposure_auth_check and tests/test_scanner_django.py::test_a_django_scan_surfaces_the_exposure_auth_check (all unmarked while this waiver stands — a marked test would claim the requirement's whole text and the escalation clause remains unbuilt). Retire the remainder when a wizard data-sensitivity question exists and public-exposure + financial/personal + no-auth escalates `core.exposure-auth` to blocker with a marked test — at which point the SCAN-M4-EXPOSURE-AUTH markers go back on. Original waiver and clause-(b) retirement both dated (2026-08-11)

WAIVED: conformance/demos/phase-1+unchecked-by-any-requirement — no phase-1 requirement is `verify: demo`, so the four artifacts under conformance/demos/phase-1/ are read by nothing: check.py only opens the paths a `demo:` key names (or the phase-N.md fallback), and the sole demo req is P0-WS-DEMO at phase 0. This is why R4-10 (the stale E-invoice scan record) did not surface when SPEC-gate-integrity.md §3.4 predicted it would — the content check landed, but no requirement points it at that tree. Retire by adding a phase-1 `verify: demo` requirement whose `demo:` names conformance/demos/phase-1/ in the registry PR (2026-08-11)

# Phase-1 demo follow-up 5 (2026-08-20): pointing the scanner at this repo is not
# a customer scan. The findings are the detector's own examples and the suite's
# fixtures. D-012, which would have labelled test material, is parked.
WAIVED: core.secret-scan+self-scan-detector-vectors — a scan of the Hub tree flags published-format examples in `scanner/modules/fallbacks.py` comments (`postgres://user:REALPASSWORD@host`) and fixture values under `tests/` and `scripts_dev/`. Those are the detector and its proofs, not leaked credentials. Phase 1's surface is customer django/node trees. Retire with D-012's return (declared test material) or a Hub-tree exclusion (2026-08-20)

# spec-mutation-gate.md §4: the mutation gate's ONLY escape hatch. There is no baseline
# file and no allowlist — a surviving mutant is a finding, fixed with a failing-first
# test, or it is one line here with its own justification. Fingerprint =
# `mutation+<file>+<mutant id>`, exactly as the gate prints it, so `mutmut show <id>`
# reproduces the diff being waived in one step.
#
# EVERY LINE BELOW CLAIMS THE SAME KIND OF THING and it is a strong claim: the mutant is
# EQUIVALENT — a different spelling of identical behaviour, so no test anywhere can
# distinguish it, and writing one would be writing a test that asserts nothing. That is
# the one honest reason to waive a survivor; "hard to test" is not, and none of these
# say it. The gate fails if any of these mutants stops surviving, so a waiver cannot
# outlive the code it excuses.
#
# THREE OF THEM WERE ALSO FINDINGS ABOUT THE CODE, recorded rather than fixed by the
# gate PR itself (deleting production code inside the PR that adds the gate judging it
# is what §6 forbids). TWO ARE NOW RETIRED, in round 9, and their lines are gone with
# them: `missing_required`'s unread first parameter and the unread `code` half of
# `validate_answers`' error entries are both deleted, so
# `wizard.materialize.x_preflight__mutmut_103`,
# `wizard.questions.x_validate_answers__mutmut_10` and `_11` no longer exist as mutants
# at all — which is the shape a retirement should take, since the gate FAILS on a waiver
# whose mutant stopped surviving.
#
# The third stands: `_read_entry`'s `normalized.startswith("/")` arm cannot fire on a
# platform where `os.sep == "/"` because `PurePosixPath.is_absolute()` already covers
# it. It is left because the arm is defensive on a platform this fleet does not deploy
# to, and deleting a guard for a case nobody here can test is a wider decision than a
# waiver retirement.
WAIVED: mutation+scanner/declarations.py+scanner.declarations.x__read_entry__mutmut_56 — equivalent mutant: `is_absolute() and startswith("/")` collapses to `is_absolute()` wherever `os.sep == "/"`, because `posix` is built from `normalized.replace(os.sep, "/")` and `PurePosixPath(s).is_absolute()` holds exactly when `s` starts with `/`. The `or ":" in parts[0]` arm is untouched and is pinned by test_each_path_refusal_says_which_rule_refused_it. Retire it by deleting the redundant arm (a round-9 finding, not a gate PR's edit), which removes the mutant with it (2026-08-16)
WAIVED: mutation+scanner/declarations.py+scanner.declarations.x__read_entry__mutmut_58 — equivalent mutant, same proof as mutmut_56: `startswith("XX/XX")` is never true, and the arm it disables is already subsumed by `posix.is_absolute()` on every platform this runs on. `/etc/secrets` is still refused as absolute, by the first arm, and that refusal is asserted (2026-08-16)
WAIVED: mutation+scanner/declarations.py+scanner.declarations.x_confirm_question_id__mutmut_19 — equivalent mutant: `"utf-8"` -> `"UTF-8"`. Python's codec lookup is case-insensitive and normalizes both to the same codec, so the digest bytes are identical. No test can tell them apart because there is nothing to tell apart (2026-08-16)
WAIVED: mutation+scanner/declarations.py+scanner.declarations.x_load__mutmut_21 — equivalent mutant: `read_text(encoding="utf-8")` -> `encoding="UTF-8"`, same case-insensitive codec lookup as the digest above (2026-08-16)
WAIVED: mutation+wizard/materialize.py+wizard.materialize.x__apply_answers__mutmut_19 — equivalent mutant: `.decode("utf-8")` -> `.decode("UTF-8")` on the vault plaintext, same case-insensitive codec lookup. Was `__mutmut_17` until R9-SEC-1 added two mutation points earlier in the same function; mutmut numbers a function's mutants in source order, so a waiver by id survives only until the function above it changes. The gate caught the stale id itself — it reported `__mutmut_17` as `killed`, which is a spent waiver — which is the property that makes renumbering safe to do by hand. First recorded 2026-08-16, renumbered on the date below (2026-08-17)
WAIVED: mutation+scanner/declarations.py+scanner.declarations.x_load__mutmut_19 — equivalent mutant in every environment this gate runs in: `read_text(encoding="utf-8")` -> `encoding=None` falls back to the locale encoding, which is UTF-8 on the dev image and on the `ubuntu-latest` runner, so the bytes decode identically. A test cannot change the interpreter's locale after start, so the difference is unobservable from inside the suite. It is NOT equivalent in principle — on a C-locale host the two differ, and there the mutant is killed by test_an_ordinary_non_ascii_reason_is_accepted rather than waived (2026-08-16)
WAIVED: mutation+scanner/declarations.py+scanner.declarations.x_load__mutmut_32 — equivalent mutant: the guard `if str(exc)` becomes `if str(None)`, and `"None"` is truthy, so the branch is taken exactly as before. It can only differ for a `yaml.YAMLError` whose `str()` is empty, and `yaml.safe_load` raises no such error — every MarkedYAMLError it constructs carries a problem string. The `else` arm it guards is unreachable defensive code (2026-08-16)
WAIVED: mutation+scanner/declarations.py+scanner.declarations.x_confirm_questions__mutmut_16 — equivalent mutant: dropping `default=None` from the `WizardQuestion(...)` call leaves the dataclass field's own default, which is `None` (scanner/core.py). R7-11's point — that an unanswered claim is not an accepted one — is unaffected, and the test that pins it stays green because the value is unchanged. Retire it by making the field have no default, which is a scanner/core.py decision, not this gate's (2026-08-16)
WAIVED: mutation+hub/renderers.py+hub.renderers.xǁContainedJSONRendererǁrender__mutmut_17 — equivalent mutant: `ensure_ascii=self.ensure_ascii` -> `ensure_ascii=None`. `self.ensure_ascii` is DRF's `JSONRenderer.ensure_ascii = not api_settings.UNICODE_JSON`, a CLASS attribute evaluated once at import to `False` on this settings, and `json.dumps` treats `ensure_ascii=None` identically to `ensure_ascii=False` (None is falsy). Both spellings therefore render byte-for-byte the same on every code point — CJK stays literal, the CONTROL_CLASS is escaped by `json_safe` regardless — so no test can separate them. Not equivalent IN PRINCIPLE: were an operator to set `UNICODE_JSON=False`, `self.ensure_ascii` would be `True` and the two would diverge — but the attribute is frozen at import and no `override_settings` reaches it after start, so the difference is unobservable from inside the suite (the same shape as the `x_load__mutmut_19` locale waiver above). Retire it by reading the setting live (`not api_settings.UNICODE_JSON`) if that flag ever needs to be honoured at runtime, at which point a `@override_settings` test kills it (2026-08-18)
