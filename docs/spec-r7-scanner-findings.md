# Spec R7-B — the rest of the round-7 queue

Round 7's remaining findings (R7-1/8/11/13/14 rode
`docs/spec-r7-enforce-declaration-acceptance.md`). Full queue with evidence:
project doc `round-7-finding-queue.md`. Every item below was demonstrated by a
reviewer with a real scan or a surviving mutation — none is speculative.

Order matters: **R7-3 and R7-4 are security findings**, R7-2 is a miss class, and the
rest are correctness or hygiene.

## R7-2 (HIGH) — a subtree the walk cannot open is silently dropped

`fallbacks._iter_files` swallows `OSError` with `continue`; `_read_text` returns
`None`. A permission-denied directory, or one that vanishes mid-walk, is skipped with
no problem line, no warning, no tier change. Demonstrated: a real AWS secret at
`prodcfg/creds.py` gives `blocker`; make `iterdir` on `prodcfg` raise
`PermissionError` and the same tree reports **`tier: ok`, "No committed secrets
found", empty detail**.

**A security gate must degrade to an honest error, never to `ok`.** Collect the paths
the walk could not read and surface them. Minimum: `core.secret-scan` reports at
**warning** tier when anything was skipped and nothing else was found, naming the
paths (capped, with a count), and says results may be incomplete. If findings exist,
the skipped list rides the detail. Decide and document whether `_read_text` failures
(unreadable *file*) join the same list — argue it either way, but say which.

Watch the blast radius: `_iter_files` is shared by several core checks. Prefer a
mechanism that gives the caller the skip list without changing every caller's shape.

## R7-3 (SERIOUS) — the declared label is delimiter-injectable

The evidence label packs four fields into one string using `[`, `]`, `"`, `—`, `:` as
delimiters, and the D-012 round-1/2 validator rejects only line-breaking and bidi code
points — **not `"` or `]`**. A reason of

    fake creds"] hardcoded prod_master_key value — "see docs

renders a declared line that reads as though it contains a **second finding**:

    drill/seed.py:1: [heuristic, declared: drill — "fake creds"] hardcoded prod_master_key value — "see docs"] hardcoded admin_password value

This is the forgery class reopening a third way: rounds 1 and 2 closed the structure
*between* lines, this is the structure *within* one.

Fix by making the label unforgeable, not by enumerating more characters — the
enumeration approach has now failed twice (round 2's own lesson). Two acceptable
shapes: refuse `"` and `]` in `reason` (cheap, consistent with the existing refusal
machinery, and a reason needs neither), or render the reason through the same
`_quote`/escape path the refusal messages already use so a parser can bound it.
Prefer the one you can defend against the *next* delimiter someone adds to the label.
Failing-first test with the verifier's exact reason string.

## R7-4 (SERIOUS) — the manifest guard misses split settings packages, the fleet's own layout

`SCANNER_KEY_FILES` recognizes a literal `settings.py`, but every repo in the fleet
uses a settings **package** (`config/settings/base.py`, `prod.py`) that
`django._settings_files` discovers by parent-directory name. So declaring
`backend/config` is **accepted**, and heuristic secrets beside `base.py` are
downgraded. Demonstrated with `backend/config/settings/prod_extras.py` holding
`stripe_secret_key`.

The guard's authority must match the discovery rule it is guarding: reject a declared
directory that contains a `settings/` package (any `*/settings/*.py`), not only a
literal `settings.py`. **Derive it from `django.py`'s own rule rather than restating
it** — the N6/N7 lesson is that two copies of a rule drift, and this finding is
exactly that drift. If deriving is not practical, add a test that fails when the two
disagree.

## R7-5 (MEDIUM) — repo-controlled YAML can crash the scan

`declarations.load` catches `yaml.YAMLError` only. 200 KB of nested `[` — under the
256 KB cap — raises `RecursionError` out of `load()`, out of `scan()`, to a CLI
traceback. The module docstring promises it "never raises for anything the scanned
repo controls"; the byte cap does not bound recursion depth. Widen the guard so the
promise is true, and say in the comment why a byte cap is not a depth cap.

## R7-6 (MEDIUM) — auto-vs-declared precedence is asserted by nothing

Mutation survived the full suite: dropping the "auto-detected test material wins"
guard relabels an auto-detected finding as declared, letting a declaration **claim
credit for a downgrade it did not make** (`("drills", 0 findings)` → `1 findings`).
The clause is in the `SCAN-DECLARED-TEST-MATERIAL` text and in a code comment; every
fixture keeps the two path sets disjoint. Add the marked test: declare a directory
that auto-detection already classes as test material, assert the finding lands in the
auto bucket and the declaration's count stays 0.

## R7-7 (MEDIUM) — multi-entry isolation is asserted by nothing

Mutation survived: making one bad entry drop all siblings turns a real scan from
`warning` to `blocker`, and **no test anywhere constructs a two-entry
`deployhub.yaml`**. Add one: `[stale-entry, valid-entry]`, assert the valid sibling
still applies and the stale one still warns.

## R7-9 (MINOR) — `scanner/declarations.py` is not on the sensitive-path list

`conformance/paths.yaml` carries `scanner/modules/**`, added because code there can
weaken `core.secret-scan`. `scanner/declarations.py` holds the same authority and
matches no glob. Add it (or broaden the glob). This edit is **its own commit** — the
path list is process machinery and does not ride a product-code commit.

## R7-10 (MINOR) — no cap on declaration count

~3000 entries fit under the byte cap → 3000 header lines and 3004 wizard questions.
`MAX_REASON_CHARS` exists to stop a wall of prose burying the count; many entries
rebuild the wall another way. Cap accepted declarations (suggest 50) with one warning
naming the count when exceeded.

## R7-12 (LOW) — `_warning_title`'s three branches collapse to one string with no test red

Assert the title in the stale-declaration test and the merge test.

## R7-15 (NOTE, cleanup) — `Declarations._by_path` is dead

Declared, never written, never read. Delete it.

## Registry (its own commit, first or last, not mixed with product code)

`SCAN-DECLARED-TEST-MATERIAL`'s `text:` says declared findings move to a "third,
**non-blocking** bucket". After R7-A that is false — they block until accepted.
Correct the text to what the tests now prove, and re-pin `text_hash` if the source
citation moves. Do not weaken either requirement while you are in there; if you think
a clause should be relaxed, stop and report instead.

## Out of round scope, fix here anyway (own commit, say so in the message)

`node_ts.py::_iter_source_files` **hangs forever on a symlinked directory loop** —
found by the SRE reviewer while testing loops. It runs during module detection, before
the secret-scan arc, and is unchanged in the round's diff, so it is not a round-7
finding; it is also a real hang an operator can hit with a repo that contains one
symlink. `fallbacks._iter_files` already handles loops correctly (prunes symlinked
directories, `resolve()` + `seen` set) — apply the same treatment and test it with a
real loop.

## Acceptance

- Failing-first regression test for every item, each verified failing before its fix.
- Over-correction guards where the fix narrows behavior: a legitimate reason with an
  apostrophe or an em dash still works (R7-3); a declared directory that merely *has*
  a subdirectory named `settings` full of non-Python files is not rejected (R7-4);
  a repo with an unreadable file that is genuinely binary does not start warning
  (R7-2).
- Full suite green, `make review-round` green, `check.py --phase 1` exit 0.
- **All five demo artifacts must be re-verified**: R7-2 may add a line to a fleet
  record if any tree has an unreadable path (it should not — check and say so), and
  R7-3/R7-4 must not move any record. `cmp` each and report.
- `scanner/**` is a sensitive path → human merge.
