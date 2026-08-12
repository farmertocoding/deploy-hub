# SPEC — R8-1 + R8-4: the operator's path through declaration acceptance

**Round:** 8 · **Findings closed:** R8-1 (high), R8-4 (serious), and — as a required
consequence, not scope creep — round-7 **carried note 5**.
**Base:** `ffec190` (master). **Branch:** `r8-operator-acceptance-path`.
**Authored by:** the round-8 finding round. **Built by:** an Implementer.
**Reviewed by:** a third session, against this spec — not against the Implementer's
account of it (build-process.md §1 delegation rule, §4 UPDATE 2026-08-09).

---

## 1. The defect, stated once

After R7-1, a declared finding blocks until the operator accepts it. The server side is
complete: `preflight` clears the blocker on a strict `True` per declaration,
`can_materialize` goes true, the manifest records the act, 680 tests pin it.

**The operator cannot get there.** `SiteWizard` receives `hasBlockers` from its parent
(`Readiness.jsx:142`, `!!report.blockers?.length`), derived from `ReadinessView`'s raw
`check["tier"]` walk, which has no acceptance filter. The stored `scan_report` is *by
design* never rewritten by an answer, and `test_issue_r7_1r_a_re_scan_that_changes_nothing_keeps_the_acceptance`
pins that re-scanning an unchanged tree changes nothing. So `report.blockers` contains
`core.secret-scan` forever, `Readiness.jsx:222` keeps the sole Materialize control
disabled, and its tooltip instructs the operator to do the one thing that provably
cannot work.

Measured on a real scanned tree: `preflight == []`, `can_materialize == True`,
`blocking == []`, `READINESS_BLOCKERS_COUNT == 1`. The only POST to
`v1/sites/{id}/manifest/` in the whole of `frontend/src` is `materialize()` at
`Readiness.jsx:171`, reachable only from that button.

And **R8-4**: no simulation fixture renders the state, so the §F8 walk — the human
review whose whole job is catching this — could not have covered it.

**The lesson this spec exists to bank:** a control can be wired, enforced, audited and
tested, and still be unreachable by the human it exists for. The fix is not complete
until the state is *reviewable*, which is why R8-1 and R8-4 are one change.

---

## 2. What to build

### 2.1 Gate the action on the authoritative field (R8-1)

`SiteWizard` already fetches `state` from `v1/sites/{id}/wizard/`, which carries
`can_materialize` (`views.py::_state`, `not problems`) and `blocking` (the preflight
problem list). **Gate on those. Stop using `hasBlockers` for the action.**

- The Materialize button's `disabled` becomes `busy || !state.can_materialize`.
- Remove the `hasBlockers` prop from `SiteWizard` entirely — do not leave it accepted
  and unused. The parent keeps `report.blockers` for the tier display; it is no longer
  an input to any action.
- `state.can_materialize` is authoritative because it is `not preflight(site)`, the same
  function the POST itself runs. Client and server then refuse for identical reasons,
  which is the property `ReadinessView`'s docstring already claims for tiering
  ("so the CLI, the UI and the pipeline all agree").

**Label and tooltip, driven by `state.blocking` codes:**

| condition | label | `title` |
|---|---|---|
| `can_materialize` true | `Materialize manifest` | `""` |
| blocking contains `blockers_present` | `⛔ Blocked` | `Blockers must be fixed and rescanned first — materialization will refuse.` |
| blocking contains only `answers_missing` (incl. the declaration confirms) | `Answer required` | `Some required questions are unanswered — including any declaration you must accept or refuse. Answering them here is what clears them; re-scanning will not.` |
| any other / mixed | `⛔ Blocked` | the joined `detail` of every `state.blocking` entry |

The third row is the R8-1 fix in copy form: the old tooltip's "fixed and rescanned" is
**false** for an acceptance-pending blocker, and telling an operator to re-run the one
operation pinned to change nothing is how this defect stayed invisible.

**Do not** invent a new endpoint, serializer field, or client-side tier computation.
Everything needed is already in the payload.

### 2.2 Render the acceptance hint on the blocker card (carried note 5)

Required, because 2.1 alone produces an incoherent screen: an enabled **Materialize
manifest** button under a red **2 blockers** heading, with nothing connecting them.

In the readiness check list (`Readiness.jsx:130-139`), when a check object carries an
`acceptance` object:

- If `acceptance.blocking_only_declared === true`: render, inside the `<details>` under
  `detail`, a line reading
  `Awaiting your acceptance — answer the declaration question${n === 1 ? "" : "s"} in the site configuration below to clear this. Re-scanning will not.`
  where `n = acceptance.questions.length`.
- If `acceptance.blocking_only_declared === false`: render
  `This check also carries findings that are not declared, so accepting the declarations will not clear it.`
- Status must not be conveyed by colour alone (§F5) — the line is text, next to the
  existing `Fix:` line, not a coloured dot.

`acceptance` reaches the client already: `ReadinessSerializer.blockers` is a
`ListField(child=DictField())`, so the field passes through untyped. **No serializer
change, therefore no `make generate-client` churn** — `make check-generated` must stay
green with no regenerated diff. If the Implementer finds it does not, stop and report;
that is a spec error, not something to work around.

### 2.3 The simulation fixture (R8-4)

build-process.md §②: *"Simulation-mode fixtures (§F8) are extended whenever a new UI
state is introduced."* Extend `frontend/src/sim.js`:

**a. `MESSY_REPORT.blockers`** gains a third entry — the acceptance-pending blocker,
shaped exactly like a real one:

```js
{ id: "core.secret-scan", tier: "blocker",
  title: "Secrets in a declared tree — your acceptance is required",
  detail: "<one declared [heuristic, declared: …] line, copied verbatim from a real scan>",
  fix_hint: "<the real fix_hint for this tier/bucket>",
  acceptance: { questions: ["scanner.test_material.frontend-scripts-drill--<16 hex>"],
                blocking_only_declared: true } }
```

The `detail`, `fix_hint` and confirm id must be **copied from a real scan**, not
invented — generate one against a fixture tree and paste. A fixture that invents copy is
a UI reviewed against a fiction, which is the exact failure `sim-contract.test.ts`'s
header comment was written about. Update `MESSY_PROJECT.tiers.blocker` to match.

**b. `WIZARD_STATE.questions`** gains the matching confirm, and `blocking` its problem:

```js
{ id: "scanner.test_material.frontend-scripts-drill--<same 16 hex>", kind: "bool",
  prompt: "<the real confirm prompt, verbatim from confirm_questions()>",
  choices: [], default: null, secret: false }
```

with the id appearing in the `answers_missing` problem's `items`. Leave it out of
`answered` — unanswered is the state under review.

**c. A post-acceptance variant.** The dead end only shows itself *after* the answer, so
the fixture must be able to render that too. Add a sixth named state,
`accepted`, that returns the same project/readiness data but a `WIZARD_STATE` with the
confirm answered `true`, `blocking: []`, `can_materialize: true` — the readiness report
still carrying the blocker-tier check with its `acceptance` field. That combination
(red blocker count + enabled button + hint explaining why) is precisely what a reviewer
must be able to look at, and it is unrenderable today.

**d. `REFUSAL_409.problems`** gains an `answers_missing` entry whose `items` include the
confirm, so the refusal path shows what an unanswered declaration looks like.

### 2.4 Pin it (`frontend/tests/sim-contract.test.ts`)

Add, alongside the existing tests:

1. `REQUIRED_STATES` gains `"accepted"`; the existing "all states exist" test covers it.
2. The `accepted` wizard state parses against `schemas.WizardState`, and the `accepted`
   readiness report parses against `schemas.Readiness`.
3. **The acceptance state is actually present**, not merely parseable — a fixture that
   silently loses the field would still parse, since `acceptance` is untyped:
   - `live` readiness has ≥ 1 blocker with an `acceptance` object whose `questions` is a
     non-empty array and `blocking_only_declared === true`;
   - every id in that `questions` array **exists as a `kind: "bool"` question** in the
     `live` `WIZARD_STATE` (this is the drift alarm: the fixture's report and its wizard
     cannot disagree about which confirm is pending);
   - the `accepted` state has `can_materialize === true` **and** still carries that
     blocker-tier check — the combination under review.

### 2.5 The regression test that would have caught R8-1

`sim-contract.test.ts` is a fixture test; it does not exercise `Readiness.jsx`. The fix
needs one test that fails on the current code. Add
`frontend/tests/materialize-gate.test.ts` (node:test, same runner as
`make test-frontend`):

- Export the gate decision as a pure function from `Readiness.jsx` — e.g.
  `export function materializeGate(state)` returning `{disabled, label, title}` — and
  test it directly. Extracting it is required, not optional: the point is that the
  decision becomes a named, testable thing rather than an expression inside JSX.
- Cases, each named for what it proves:
  - `can_materialize: true` with a blocker-tier check present in the report → **enabled**,
    label `Materialize manifest`. **This case fails on `ffec190`** — it is the regression
    test for R8-1 and must be written first and seen red.
  - `blocking: [answers_missing]` → disabled, label `Answer required`, tooltip contains
    neither the word "rescan" nor "rescanned".
  - `blocking: [blockers_present]` → disabled, `⛔ Blocked`, old tooltip.
  - mixed → disabled, joined details.

Naming: follow the repo's convention — `test_issue_r8_1_*` style, adapted to the TS
runner's `test("r8-1: …")`.

---

## 3. Out of scope — do not touch

`wizard/views.py`, `wizard/materialize.py`, `scanner/**`, any serializer, any
requirement id, `conformance/requirements.yaml`, `REVIEW_CHECKLIST.md`, any gate script
or Makefile target. The server side of this flow is correct; only the client and the
fixtures are wrong. R8-2, R8-3, R8-5..R8-16 are separate PRs.

If the Implementer believes a server change is needed, **stop and report it as a spec
defect** rather than widening the diff — a round-8 remedy that quietly edits the gate it
is judged by is the §4 anti-gaming case.

---

## 4. Definition of done

- `frontend/tests/materialize-gate.test.ts` was seen **red on `ffec190`** and is green
  after (state the observed red output in the commit message — a regression test nobody
  watched fail is R4-11's class).
- `make test-frontend` green, `make check-generated` green **with no regenerated diff**,
  `make lint`, `make log-scrub`, `pytest -q` **680 passed** (unchanged — this diff touches
  no Python), `check.py --phase 1` exit 0.
- Walking `?sim=live` shows: a red blocker count, the acceptance hint on the
  `core.secret-scan` card, an unanswered `bool` confirm in the site configuration, and a
  disabled **Answer required** button whose tooltip does not say "rescan".
  `?sim=accepted` shows the same report with an **enabled** Materialize button.
- No `hasBlockers` prop remains anywhere.
- One commit per finding where the split is honest; `docs/` spec included.

## 4b. SPEC DEFECT — §2.1's table was wrong, and the correction is the finding

**Filed by the reviewing session, confirmed against `wizard/materialize.py::preflight`
by the spec's author. This supersedes §2.1's table and parts of §2.3.**

§2.1 assumed an acceptance-pending blocker arrives as `answers_missing`-only. It does
not. `preflight` emits **`blockers_present`** for it, with each pending check carrying an
`awaiting_acceptance` list — *and then appends the truthful clause to its own detail*:

> "the readiness report has blockers; these must be fixed and the project re-scanned —
> **except where a declaration is awaiting acceptance, which you clear by answering its
> confirm in this wizard, not by changing the repo**"

with this comment sitting directly above it in the server source:

> `# §3: name what is being waited on. "Fix them and re-scan" is the wrong instruction`
> `# for this one — there is nothing in the repo to fix and the re-scan produces the`
> `# identical report forever.`

**So the correct copy already existed, in the payload, written by someone who knew
exactly why the old tooltip was false — and the client threw it away for a hardcoded
string.** That is R8-1's own shape one layer down, and it makes the rule for this fix
plain:

> **Never hardcode a refusal string the server already sends.**

Under the original table, the "Answer required" branch keyed on `answers_missing` and is
therefore **unreachable on any real server**; the built branch still shows
"⛔ Blocked / Blockers must be fixed and rescanned first" in exactly the case R8-1 exists
to remove, and `?sim=live` passed only because the fixture carried a `blocking` shape no
server sends. My error, not the Implementer's — they flagged the conflict and I had told
them the wrong thing.

### 4b.1 The gate, restated (replaces §2.1's table)

From `state.blocking`, let `hard` = the `blockers_present` items that carry **no**
`awaiting_acceptance` key.

| condition | `disabled` | label | `title` |
|---|---|---|---|
| `state.can_materialize` | false | `Materialize manifest` | `""` |
| a `blockers_present` entry exists and `hard.length === 0` | true | `Answer required` | the **server's own** joined `detail` of every `state.blocking` entry |
| otherwise | true | `⛔ Blocked` | the **server's own** joined `detail` of every `state.blocking` entry |

Rows two and three now differ only in the label; both take their tooltip from the
payload. No refusal string is authored in the client — delete the two hardcoded ones.
The label split still earns its keep: it is the one thing the server does not say in a
word, and it is what a scanning eye reads before the tooltip.

### 4b.2 Fixtures rebuilt from real output (replaces §2.3b/c, keeps §2.3a/d)

The reviewer measured that **both** `?sim=live`'s and `?sim=accepted`'s wizard `blocking`
are shapes no server sends for `MESSY_REPORT` — `preflight` keeps `blockers_present` for
the two undeclared `django.*` blockers no matter what is answered. §2.3c's `accepted`
precedent was the same fiction one step earlier. Both are wrong; do not preserve either.

- Add a **third fixture project** whose *only* blocker is the acceptance-pending
  `core.secret-scan` — `tiers: { blocker: 1, … }`, one site. That project is what makes
  the pending state and the accepted state both real: declared-only + confirm unanswered
  → `blockers_present` with `awaiting_acceptance`; confirm answered → `preflight == []`.
- Restore `MESSY_PROJECT`'s wizard `blocking` to what `preflight` actually returns for
  its report, with the acceptance-pending `core.secret-scan` blocker among its
  `blockers_present` items. It is then the honest **mixed** case — one blocker an answer
  clears, two it never will — and it exercises row three.
- Every `blocking` entry, and every `detail` in it, is **copied from a real `preflight`
  run**, not written. Put the command that produced it in a comment above the fixture.
- Delete the `sim.js` comment that explains the held-out `blockers_present`. It was
  candid about the shallower half of a fiction that no longer exists.

### 4b.3 The 409 becomes reachable again (Finding 3)

On `ffec190` the clean project's enabled button reached `REFUSAL_409`; on the branch no
sim state can fire the POST, so §2.3d's own edit is reviewable nowhere — R8-4's class,
reintroduced by the change closing R8-4. Model the one state that really produces a
client-allowed 409: **stale wizard state** — the GET said `can_materialize`, a re-scan
added a blocker before the POST. Add sim state `stale`: wizard says go, manifest POST
returns `REFUSAL_409`, whose strings are copied from a real `preflight` (the current
`blockers_present.detail` in that fixture is not one the server sends).

### 4b.4 Additional pins

- `sim-contract.test.ts`: every blocker-tier check carrying `acceptance` in a state's
  readiness report must appear in that state's wizard `blocking` as a `blockers_present`
  item with a matching `awaiting_acceptance` — and vice versa. This is the alarm that
  would have caught the fiction, and it must go red when either side is edited alone.
- `materialize-gate.test.ts`: a case built from the **real** pending payload
  (`blockers_present` + `awaiting_acceptance`, no `answers_missing`) asserting
  `Answer required` and a tooltip containing the server's "not by changing the repo"
  clause. **This case fails on the branch as built** — it is the regression test for this
  spec defect.
- A case asserting the mixed shape (one `awaiting_acceptance` item, one without) gives
  `⛔ Blocked`.
- No string literal in `Readiness.jsx` duplicates a `detail` the server sends; grep for
  "rescanned" and "re-scanned" in `frontend/src` and expect nothing.

### 4b.5 Ruled: the `?sim=accepted` 201 handler stays

The Implementer added it beyond the spec so the enabled button does not 404 on a
reviewer's click. The reviewer judged it required for coherence and verified the body is
a real materialize output. Agreed — keep it, on the new fixture project.

---

## 5. What the reviewing session should attack

- Does `materializeGate` actually get used by the rendered button, or does JSX still
  compute its own `disabled`? (A pure function nobody calls is R7-1's shape in
  miniature — the whole reason this spec asks for the extraction.)
- Is the `accepted` fixture reachable from the UI (`?sim=accepted`), or only from the
  test?
- Does the drift alarm in §2.4 item 3 actually go red if the confirm id in
  `MESSY_REPORT` and the one in `WIZARD_STATE` are edited apart? Break it and check.
- Does any tooltip or hint state something the server does not do? Read each string
  against `preflight` and `_pending_acceptance` — R8-10 and R8-11 are both false-copy
  findings from the last remedy, and R7-1's `fix_hint` was false and shipped.
