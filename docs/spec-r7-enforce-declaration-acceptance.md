# Spec R7-A — the declaration downgrade must be the operator's act (round-7 veto)

**Ruled by Joseph, 2026-08-12, on the security expert's veto (R7-1):** *no acceptance,
no downgrade.* Three reviewers found independently that D-012's trust model has only
one of its three controls. This spec makes the other two real.

## What is wrong today

The downgrade is applied at scan time from a repo-controlled `deployhub.yaml`. The
wizard confirm exists but is not in `REQUIRED_IDS`, its answer is written to
`body["module_answers"]` and read by no code in the repo, refusing it changes nothing,
and `manifest_draft["declared_test_material"]` is populated unconditionally from the
scan draft — so the audit artifact asserts an acceptance that may never have happened.
The blocker-tier `fix_hint` states that "refusing it is how you say the declaration is
wrong", which is false.

## The rule

A declaration is a **request**. Until the operator accepts it, the findings under it
block exactly as they did before D-012 existed. Acceptance is per declaration,
recorded from the answer, and refusable with effect.

## 1. The scan reports honestly — declared findings still block

`_check_secret_scan` keeps the three buckets and the header (they are how the operator
reads the claim), but the **tier no longer drops on account of a declaration**:

- Declared findings count toward blocking. A repo whose only blocking evidence is
  declared reports **tier `blocker`** with its own title — suggested
  `"Secrets in a declared tree — your acceptance is required"` — and detail that
  explains, in one sentence, that accepting the declaration in the wizard is what
  clears them. Wording is the implementer's; it must be true.
- The `Declared test material (…)` section header must stop saying "not blocking"
  while unaccepted. Suggested: `Declared test material (downgrade requested by
  deployhub.yaml — blocks until you accept it in the wizard):`.
- Nothing else about bucket routing, labels, or the `[proof]`/`.env` scope changes.

**The scanner has no answers and must not pretend to.** It states what is claimed and
what it would take to clear it; the wizard owns the acceptance.

## 2. A small structured contract, so the wizard need not parse prose

`CheckResult` gains one optional field, serialized in `as_dict()` (name is the
implementer's; shape is not):

    acceptance = {
      "questions": ["scanner.test_material.1.frontend-scripts-drill", ...],
      "blocking_only_declared": true|false,
    }

- `questions` — the confirm ids that, answered `True`, accept every declaration whose
  findings this check downgraded.
- `blocking_only_declared` — `True` when the check's blocking evidence is **entirely**
  declared findings, i.e. accepting them all leaves nothing blocking. `False` when a
  real blocker (a `[proof]` line, a `.env` file, an undeclared heuristic line) is also
  present.

This is deliberately the minimum structure needed; the §F2 findings array is a later,
separate change (round-7 note).

## 3. Preflight enforces it

In `wizard/materialize.py::preflight` (and anything else gating on
`tier == "blocker"`):

- A blocker check with `acceptance.blocking_only_declared == True` **stops blocking
  when every id in `acceptance.questions` is answered `True`** in the site's stored
  answers.
- While any of them is unanswered or `False`, the existing `blockers_present` problem
  stands, and its `items` must name the declaration(s) awaiting acceptance so the
  operator can see what to do.
- `blocking_only_declared == False` is unconditional — acceptance never clears a real
  blocker. Guard test required.

## 4. The confirm is required when there is something to confirm

`REQUIRED_IDS` is a static set and the declaration ids are per-project, so extend
`missing_required` (or its caller) to treat every `scanner.test_material.*` question
in the project's question set as required. Unanswered → materialization refuses, same
shape as a missing `site.domain`.

## 5. The manifest records what the operator accepted, not what the repo asked for

`materialize` must build `body["declared_test_material"]` from the **answers**: only
declarations whose confirm is `True`, each carrying the answer that accepted it.
A refused declaration is recorded as refused, not dropped silently — an audit trail
that omits refusals is the same defect in a different direction. `scan()` may keep
emitting the draft list, but the frozen manifest is the answer-derived one.

## 6. Copy (round-7 R7-8, and the false sentence)

- The blocker-tier `fix_hint` currently claims refusal is meaningful; after this
  change it is — make the sentence true and specific about what refusing does.
- The blocker path must carry the declared/downgrade legend at all. Today the
  explanation exists only on the warning tier, so on SATURDAYS_site — the motivating
  repo — the operator sees `[heuristic, declared: …]` lines and a "Downgrades claimed"
  header with nothing telling them what that means. Add the legend to the
  `[proof]`/`[heuristic]` explanation whenever any declaration was applied.

## 7. Small items riding this branch

- **R7-11:** assert `default is None` on the confirm question — the "an unanswered
  claim is not an accepted one" property is claimed in the record and pinned by
  nothing (mutation to `True` survives the suite).
- **R7-13:** `deployhub.yaml` is parsed **twice** per scan (once for the check, once
  for questions/manifest) against a comment claiming "parsed once; two readers below".
  Load once in `scan()` and thread it through, or have `common_checks` return the
  `Declarations` it used. Two reads of a repo-controlled file can diverge mid-scan.
- **R7-14:** move `_declaration_questions` out of `scanner/core.py` into
  `scanner/declarations.py`. D-010 made core the *composer*; the prompt copy, the slug
  scheme and the `_env_name` defense belong with the validation rules. `scan()` calls
  it and extends.

## Acceptance

- Failing-first regression tests for every clause, including these guards:
  **(a)** a declared-only repo reports `blocker` before acceptance and the deploy is
  refused; **(b)** the same repo with every confirm answered `True` passes preflight;
  **(c)** answering `False` keeps it blocked and the manifest records the refusal;
  **(d)** a repo with a real `[proof]` finding inside a declared tree stays blocked
  **with every confirm answered True** (`blocking_only_declared == False`);
  **(e)** an unanswered confirm refuses materialization; **(f)** the manifest never
  contains a declaration the operator did not accept.
- Full suite green, `make review-round` gates green, `check.py --phase 1` exit 0.
- **The four fleet demo records and `scan-sample-node-site.json` WILL move** for
  SATURDAYS_site (tier and section wording) and must be re-recorded on this branch;
  the other three and the fixture must stay byte-identical — verify with `cmp` and say
  so. Re-record by scanning `/home/claude/fleet/<name>`.
- `conformance/demos/phase-1.md` narrative updated: the D-012 section must state the
  round-7 correction plainly rather than quietly changing numbers.
- `wizard/**` and `scanner/**` are sensitive paths → human merge, and this spec ships
  with the branch.
