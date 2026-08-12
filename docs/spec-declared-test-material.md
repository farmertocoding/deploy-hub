# Spec — declared test-material trees (follow-up 2, ruled by Joseph 2026-08-11)

**The ruling.** A repo declares its drill/QA trees in a config file checked into the
scanned repo itself; the wizard reads it, and the scan report must always show that a
downgrade was claimed and by which declaration. Hub-side operator waivers and
keep-it-a-blocker were considered and not chosen. Path-based *name* lists (the scanner
guessing from `drill/` etc.) stay ruled out per round-6b. This spec turns the ruling
into buildable shape; it is NOT implemented yet.

**Motivating measurement** (`phase-1-demo-records-and-d011r-data.md`): 20 of
SATURDAYS_site's 26 blocking heuristic lines are `frontend/scripts/drill/**` — QA and
red-team scripts holding deliberate `admin_password` literals. Test material by intent
and content, but not by path, so `core.secret-scan` has no honest way to know.

## The file

`deployhub.yaml` at the scan root (the scanner's config surface generally; this spec
defines only one key):

```yaml
scanner:
  test_material:
    - path: frontend/scripts/drill
      reason: red-team / QA drill scripts; deliberate fake credentials
```

Rules:

- `path` is a directory, relative, inside the tree, no `..`, no glob, must exist in
  the scanned tree. A missing path is a **warning-tier finding** naming the stale
  declaration (a declaration that outlives its tree is exactly the kind of rot the
  report must surface).
- `reason` is mandatory, non-empty. It is copied verbatim into the report.
- Declaring the scan root (`.` / `/`) or a path that contains the manifest/settings
  files the scanner keys on is **rejected** — the declaration becomes a warning and
  the downgrade does not happen. A declaration that swallows the whole repo is
  indistinguishable from hiding.

## What a declaration does — and does not — change

**ERRATUM (round 7, 2026-08-12):** "the non-blocking bucket" below is no longer true and
is left in place because this text is cited and hashed. Joseph's ruling on the security
expert's R7-1 veto — `docs/spec-r7-enforce-declaration-acceptance.md §1` — is that a
declaration is a *request*: the routing into the third bucket is unchanged, and those
findings **block until the operator accepts the declaration in the wizard**. Read the
bullet below as "routes findings … into the third bucket"; the tier no longer drops on
account of a declaration.

Mirrors N6's axis scoping exactly:

- The **heuristic axis** of `core.secret-scan` routes findings under a declared path
  into the non-blocking bucket, labelled
  `[heuristic, declared: <path> — "<reason>"]` — a third bucket beside auto-detected
  test material, never silently merged with it.
- The **`[proof]` axis and the `.env` handler still run at full tier** under declared
  paths. A real `ghp_…` token in a drill script is a real token; drills should use
  fake-format values.
- No other check reads the declaration. (`core.gitignore`, `core.exposure-auth`, the
  django/node modules: unaffected. Scope can widen later by decision, not by drift.)

## The report shows the claim

- The check's detail gains a header line when any declaration was applied:
  `Downgrades claimed by deployhub.yaml: <path> ("<reason>", N findings)` — present
  even when N=0, so a reader always sees that the repo asserted something about
  itself.
- The wizard surfaces each declaration as a confirm step ("this repo declares
  `frontend/scripts/drill` as drill material — accept?"), and the materialized
  manifest records the accepted declarations, so the acceptance is the operator's,
  logged, per §F5 action-tier friction.

## Conformance & process

- New requirement ids (registry edit in its own PR per the anti-gaming rule):
  `SCAN-DECLARED-TEST-MATERIAL` (behavior + labels + report header) and
  `SCAN-DECLARED-GUARDS` (root-declaration rejection, missing-path warning, proof
  axis unaffected).
- Tests, failing-first: declared tree downgrades with label; undeclared identical tree
  still blocks; `ghp_` token inside declared tree still `[proof]`-blocks; declaration
  of `.` rejected with warning; missing path warns; report header present with and
  without findings; SATURDAYS_site-shaped fixture (drill dir with `admin_password`
  literals) as the realism case.
- `scanner/modules/**` is on the sensitive-path list → human merge; and this makes
  `core.secret-scan` quieter → **mandatory independent adversarial pass, misses over
  noise**, per the standing rule (three prior incidents).
- After it lands: re-scan SATURDAYS_site with a proposed declaration, expect 26 → 6
  blocking lines, and only then close D-011r's noise question for good.

## Open sub-questions deliberately left to the implementer/reviewer

- YAML vs TOML: YAML chosen here because the repo's other operator-facing surfaces
  (compose, CI) are YAML; revisit only if the parser dependency is objectionable.
- Whether `deployhub.yaml` itself should be schema-validated wholesale now or
  key-by-key as keys appear (this spec needs only `scanner.test_material`).
