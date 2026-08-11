"""The single implementation of "what are the gates, and does CI actually run them?".

Round-5 left this open as N1: `conformance/check.py` and `tests/test_gate_parity.py`
each grew their own answer, of differing strictness. check.py asked only "does the
string `make <target>` appear in some `run:`", while the parity test — after round-5 F2 —
also required the step to be exactly one bare `make` call, with no `&&`, no trailing
arguments, no `continue-on-error:` and no `if:`. So a workflow could neuter a gate step
and `check.py` would go on reporting the requirement it guards as `verified`, while the
parity test failed. Two implementations of one rule, drifting apart, is precisely the
R4-8/R4-12 defect class one level up: the gate machinery reproducing the defect it exists
to kill.

This module is that one implementation. `check.py` and the tests both import it; neither
re-derives any of it. Everything here takes a repo root so the gate's own tests can point
it at a throwaway tree.

It also owns three other things that were being parsed in more than one place, or in one
place too loosely:

  * `parse_waivers` — WAIVERS.md. check.py used a parser without an end anchor and
    dropped anything unparseable in silence; the parity test used a stricter one. A line
    that fails to parse is now a reportable problem, never a silently-absent waiver.
  * `tree_fingerprint` — what a run report is bound to. Round-5 bound it to
    `git rev-parse HEAD`, so any uncommitted edit made after the suite ran left a report
    that still looked fresh.
  * `PR_ONLY_GATES` — the narrow, declared exemption to the `if:` ban (N3).
"""
import hashlib
import pathlib
import re
import subprocess

import yaml

# ── Makefile: the single declaration of the gate list ───────────────────────

MAKE_CALL_RE = re.compile(r"\bmake\s+(?:-[A-Za-z-]+\s+)*([A-Za-z0-9_.-]+)")

# A gate step is one command: `make <target>`, optionally with make's own flags. Anything
# that joins a second command to it can change the verdict (round-5 F2).
BARE_MAKE_RE = re.compile(r"^make((?:\s+-[A-Za-z-]+)*)\s+([A-Za-z0-9_.-]+)$")
SHELL_JOINERS = ("&&", "||", ";", "|")

# Round-6 verifier F1: round 5 wrote `(?:\s+-[A-Za-z-]+)*` for "make's own flags" and
# left it at that, so `run: make --dry-run lint` read as a bare, honest invocation —
# and a dry run prints the recipe and exits 0 without executing it. So do `-i`
# (ignore-errors), `-q` (question mode, exit status only), `-t` (touch), `-o` (pretend
# a prerequisite is old). Each is a gate that CI reaches and does not run: the same
# false green as `continue-on-error: true`, arriving through the syntax the parity test
# was built to bless.
#
# Allow-list, not deny-list. A deny-list has to be right about every make flag that
# exists now and every one added later; an allow-list only has to be right about the
# two that are actually useful in CI, and a new one is a reviewable edit here.
ALLOWED_MAKE_FLAGS = frozenset({"-s", "--silent", "--quiet", "--no-print-directory"})


def makefile_text(root):
    mk = pathlib.Path(root) / "Makefile"
    return mk.read_text(encoding="utf-8") if mk.exists() else ""


def _text(root, text):
    return makefile_text(root) if text is None else text


def phony_targets(root=None, text=None):
    """The `.PHONY:` target list (line continuations included)."""
    out = set()
    for m in re.finditer(r"^\.PHONY:((?:[^\n]*\\\n)*[^\n]*)", _text(root, text), re.M):
        out.update(m.group(1).replace("\\", " ").split())
    return out


def makefile_targets(root=None, text=None):
    """Every target the Makefile declares, read from the file as it stands.

    Deliberately not a hard-coded list: a concurrently-added target must be recognised
    the moment it lands.
    """
    targets = set()
    for line in _text(root, text).splitlines():
        if not line or line.startswith(("\t", " ", "#")):
            continue
        m = re.match(r"^([^:#=]+):(?!=)", line)
        if not m:
            continue
        for name in m.group(1).split():
            if not name.startswith("."):  # .PHONY / .DEFAULT_GOAL are not gates
                targets.add(name)
    return targets


def review_round_prerequisites(root=None, text=None):
    """The gate set, read from `review-round`'s prerequisite list.

    Round-5 F8: a hand-typed gate list is the R4-12 defect declared a third time.
    `review-round` is what a round actually executes, so it is the one place the gate
    list is stated and every other consumer derives from it.
    """
    m = re.search(r"^review-round:((?:[^\n]*\\\n)*[^\n]*)", _text(root, text), re.M)
    return set(m.group(1).replace("\\", " ").split()) if m else set()


def pr_only_gates(root=None, text=None):
    """Gates declared as impossible to run on a plain push (N3).

    A gate that compares a branch against its merge base — the `sensitive-path-guard`
    of D-001 is the live example — has nothing to compare on a `push` event. The
    blanket `if:` ban of round-5 F2 leaves such a gate no legal shape at all: run it
    unconditionally and it is meaningless on push; guard it with `if:` and the parity
    test calls it neutered.

    So the exemption is *declared*, in the same file that declares the gate list, and
    it is narrow: see `gate_step_violations` for what a declared PR-only gate is still
    not allowed to do.
    """
    # Two ways this reader used to declare nothing while looking like it declared
    # something, both found by running it:
    #   * `[ \t]*`, not `\s*` — `\s` matches newlines, so an EMPTY declaration
    #     (`PR_ONLY_GATES :=`) ran on into the blank line after it and read the next
    #     comment line as its value. That is the state this repo ships in.
    #   * `export` / `override` prefixes and the `?=` / `+=` / `::=` assignment forms
    #     (round-6 F6) slipped past the `^` anchor, silently un-declaring an exemption
    #     its author had written. Every form contributes, so `+=` accumulates.
    declared = set()
    for m in re.finditer(
            r"^(?:(?:export|override)[ \t]+)*PR_ONLY_GATES[ \t]*[:?+]{0,2}=[ \t]*([^\n]*)",
            _text(root, text), re.M):
        declared.update(m.group(1).split())
    return declared


def recipe(root, target):
    """The recipe lines of one Makefile target, as a single string."""
    m = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)",
                  makefile_text(root), re.M)
    return m.group(1) if m else ""


# ── workflows ───────────────────────────────────────────────────────────────

def workflow_paths(root):
    wf_dir = pathlib.Path(root) / ".github/workflows"
    if not wf_dir.is_dir():
        return []
    return sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml"))


def _document(path):
    try:
        doc = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) else {}


def steps(path):
    """Yield (job_name, job, step_name, step) for every step carrying a `run:`.

    The name a step is yielded under is unique within its job: round-6 F5 found that
    steps are addressed by name downstream, so two steps a job gives the same name were
    indistinguishable and a broken one suppressed its honest namesake. A duplicated name
    gains its position; a unique one is left alone, so failure messages keep reading the
    way the workflow does.
    """
    doc = _document(path)
    for job_name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        raw = []
        for index, step in enumerate(job.get("steps") or [], 1):
            if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                continue
            raw.append((index, step.get("name") or step.get("uses") or f"step #{index}",
                        step))
        counts = {}
        for _index, name, _step in raw:
            counts[name] = counts.get(name, 0) + 1
        for index, name, step in raw:
            yield job_name, job, (name if counts[name] == 1 else f"{name} #{index}"), step


def triggers(path):
    """The event names in a workflow's `on:` block.

    `on: [push, pull_request]`, `on: {pull_request: {...}}` and the YAML-1.1 gotcha
    where a bare `on:` key parses as the boolean True all end up here.
    """
    doc = _document(path)
    raw = doc.get("on", doc.get(True))
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(x) for x in raw}
    if isinstance(raw, dict):
        return {str(k) for k in raw}
    return set()


def run_commands(run):
    """The meaningful command lines of a `run:` block (comments and blanks dropped)."""
    return [line.strip() for line in run.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def strip_comment(command):
    """Drop a trailing shell comment (` # ...`), which is inert to the shell."""
    return re.sub(r"(^|\s)#.*$", "", command).strip()


def bare_make_target(command):
    """The target of `command` if it is exactly one honest `make <target>` call, else None.

    Round-5 F2: `make lint && pytest -q --no-header || true` starts with `make ` and
    used to be waved through. It is two commands, the second of which decides the exit
    status.

    Round-6 F1: and `make --dry-run lint` is one command that does not run the gate.
    Only `ALLOWED_MAKE_FLAGS` may appear. NOTE that `-q` is make's *question* mode and
    is refused, while `--quiet` is a synonym for `-s` and is allowed — they are not the
    long and short spelling of one flag.
    """
    m = BARE_MAKE_RE.match(strip_comment(command))
    if not m:
        return None
    if set(m.group(1).split()) - ALLOWED_MAKE_FLAGS:
        return None
    return m.group(2)


def rejected_make_flags(command):
    """The flags in `command` that disqualify it as a gate invocation (round-6 F1)."""
    m = BARE_MAKE_RE.match(strip_comment(command))
    return sorted(set(m.group(1).split()) - ALLOWED_MAKE_FLAGS) if m else []


# The only `if:` expressions a declared PR-only gate may carry. Frozen, because the
# point of the exemption is to scope a gate to pull requests — not to open `if:` back
# up. `if: github.ref == 'refs/heads/main'` is the neutering round-5 F2 caught, and it
# is still a violation on a PR-only gate.
PR_SCOPING_EXPRESSIONS = frozenset({
    "github.event_name == 'pull_request'",
    'github.event_name == "pull_request"',
})


def normalize_if(expression):
    """`${{ github.event_name == 'pull_request' }}` -> `github.event_name == 'pull_request'`."""
    text = str(expression).strip()
    m = re.fullmatch(r"\$\{\{(.*)\}\}", text, re.S)
    if m:
        text = m.group(1)
    return re.sub(r"\s+", " ", text).strip()


def _conditional_problem(scope, mapping, gated, pr_only, workflow_triggers):
    """`if:` on a gate step or its job — a violation unless N3's exemption applies."""
    if "if" not in mapping:
        return None
    expression = normalize_if(mapping["if"])
    undeclared = sorted(set(gated) - set(pr_only))
    if undeclared:
        return (
            f"{scope} carries an `if:` expression ({expression!r}) and gate(s) "
            f"{', '.join(undeclared)} are not declared in the Makefile's PR_ONLY_GATES "
            f"— a gate CI can skip is a gate that does not guard the branch. Declared "
            f"PR-only today: {sorted(pr_only) or '(none)'}"
        )
    if expression not in PR_SCOPING_EXPRESSIONS:
        return (
            f"{scope} carries an `if:` expression ({expression!r}) that is not one of "
            f"the PR-scoping expressions a PR-only gate may use "
            f"({sorted(PR_SCOPING_EXPRESSIONS)}) — the exemption exists to scope a gate "
            f"to pull requests, not to make gates conditional in general"
        )
    if "pull_request" not in workflow_triggers:
        return (
            f"{scope} scopes gate(s) {', '.join(sorted(gated))} to pull requests, but "
            f"the workflow does not trigger on `pull_request` (triggers: "
            f"{sorted(workflow_triggers) or '(none)'}) — so the gate never runs at all"
        )
    return None


def _swallow_problem(scope, mapping):
    """`continue-on-error:` on a gate step or its job. Never exempt: it does not scope
    when the gate runs, it discards the verdict when it does."""
    cont = mapping.get("continue-on-error")
    if cont is not None and cont is not False and str(cont).strip().lower() != "false":
        return f"{scope} carries `continue-on-error: {cont}`"
    return None


# GNU make reads its flags from the environment as well as from argv, so everything
# ALLOWED_MAKE_FLAGS exists to stop is reachable without touching the command line:
# `MAKEFLAGS: -n` prints the recipe and exits 0, `MAKEFLAGS: i` runs it and ignores the
# failure. Round-6 N1 reproduced exactly that against the real tool, at workflow, job
# and step scope, with the parity test and check.py both green.
#
# Banned outright rather than filtered through the allow-list. There is no CI need to
# set make's flags out of band, and "which values of MAKEFLAGS are harmless" is a
# question this gate should not have to keep answering — the same reasoning that made
# the flag rule an allow-list in the first place.
MAKE_ENV_VARS = ("MAKEFLAGS", "GNUMAKEFLAGS", "MAKEFILES")

# This check is the early, reviewable signal — it catches the honest mistake in the diff
# that adds it. It is NOT the last line of defence, and it cannot be: GitHub Actions lets
# any earlier step set an environment variable for every later step by writing to
# $GITHUB_ENV, which appears in no `env:` block that any amount of workflow parsing could
# read. The Makefile refuses to start when make's own inputs carry a recipe-suppressing
# flag, whatever route it took; see the guard at the top of the Makefile, and
# tests/test_gate_followup.py::test_issue_r8_* which proves it fires.


def _make_env_problem(scope, mapping):
    env = mapping.get("env")
    if not isinstance(env, dict):
        return None
    for name in MAKE_ENV_VARS:
        if name in env:
            return (f"{scope} sets `env: {name}: {env[name]}` — GNU make reads its flags "
                    f"from the environment, so this can turn the gate into a dry run "
                    f"(`-n`), make it ignore its own errors (`-i`), or run nothing at "
                    f"all (`-q`), without the command line ever showing it")
    return None


def gate_step_problems(workflow, required_targets, pr_only=frozenset()):
    """`[(job_name, step_name, (gate targets...), message)]` — the structured form.

    `gate_step_violations` is the message-only view the parity test asserts on;
    `check.py` needs to know *which gate* each problem disqualifies, so that a
    requirement whose gate did not resolve can be told why in the same breath.
    """
    workflow = pathlib.Path(workflow)
    wf_triggers = triggers(workflow)
    document = _document(workflow)
    problems = []
    for job_name, job, step_name, step in steps(workflow):
        commands = run_commands(step["run"])
        targets = {t for line in commands for t in MAKE_CALL_RE.findall(line)}
        gated = sorted(targets & set(required_targets))
        if not gated:
            continue
        where = f"{workflow.name}: job '{job_name}': step '{step_name}'"
        gates = ", ".join(gated)

        found = []
        if len(commands) != 1:
            found.append(
                f"{where}: invokes gate(s) {gates} inside a {len(commands)}-command "
                f"run block (offending token: {commands[0]!r}) — a gate step must be "
                f"exactly one `make <target>` call so its exit status is the step's")
        else:
            command = strip_comment(commands[0])
            if bare_make_target(command) is None:
                joiner = next((j for j in SHELL_JOINERS if j in command), None)
                flags = rejected_make_flags(command)
                token = (joiner or (" ".join(flags) if flags else None)
                         or command[len("make"):].strip().split(" ", 1)[-1])
                found.append(
                    f"{where}: invokes gate(s) {gates} as {command!r} (offending "
                    f"token: {token!r}) — a gate step must be exactly one "
                    f"`make <target>` call: no {' '.join(SHELL_JOINERS)}, no "
                    f"trailing arguments")

        for scope, mapping in ((f"step '{step_name}'", step),
                               (f"job '{job_name}'", job),
                               (f"workflow {workflow.name!r}", document)):
            for problem, token in (
                (_swallow_problem(scope, mapping), "continue-on-error"),
                (_conditional_problem(scope, mapping, gated, pr_only, wf_triggers), "if"),
                (_make_env_problem(scope, mapping), "env"),
            ):
                if problem:
                    found.append(
                        f"{where}: invokes gate(s) {gates} but {problem} (offending "
                        f"token: {token!r}) — CI that reaches a gate and then ignores "
                        f"its verdict has no gate")

        problems.extend((job_name, step_name, tuple(gated), message)
                        for message in found)
    return problems


def gate_step_violations(workflow, required_targets, pr_only=frozenset()):
    """Ways a workflow step could invoke a required gate without obeying it.

    A step that calls one of `review-round`'s gate targets must be exactly one
    `make <target>` command, and neither it nor its job may swallow its verdict or make
    it conditional — except by N3's declared PR-only exemption. Steps that call no gate
    target are none of this check's business: `cd frontend && npm ci` is a perfectly
    good setup step.
    """
    return [message for _job, _step, _gated, message
            in gate_step_problems(workflow, required_targets, pr_only)]


def ci_gate_invocations(root, required_targets=None, pr_only=None):
    """`({target: [where]}, {target: [why it does not count]})` for the whole repo.

    This is the answer to "does CI run this gate", and check.py's `gate:` resolution
    reads it. A step with any violation contributes nothing: round-5 F3 established
    that naming a gate is not running it, and N1 is the same point one step further —
    a gate invoked behind `continue-on-error: true` is named, not run.
    """
    root = pathlib.Path(root)
    required = (review_round_prerequisites(root) if required_targets is None
                else set(required_targets))
    only = pr_only_gates(root) if pr_only is None else set(pr_only)

    invoked, rejected = {}, {}
    for workflow in workflow_paths(root):
        # Round-6 F7: a gate CI can only run by hand does not guard the branch. Trigger
        # awareness arrived with N3 but was consulted only on the exemption path, so an
        # honest `make lint` in a `workflow_dispatch`-only file resolved the gate.
        wf_triggers = triggers(workflow)
        if not wf_triggers & {"push", "pull_request"}:
            # Round-6 F7 residual: this used to record an empty list, so the failure said
            # "no workflow step invokes make lint" and never said which workflow was
            # skipped or why. Name it: the author whose only gate lives in a dispatch-only
            # file gets the answer instead of a hunt.
            for _job, _j, step_name, step in steps(workflow):
                for line in run_commands(step["run"]):
                    for target in set(MAKE_CALL_RE.findall(line)) & required:
                        rejected.setdefault(target, []).append(
                            f"{workflow.name}: step '{step_name}' invokes `make {target}`, "
                            f"but the workflow triggers on "
                            f"{sorted(wf_triggers) or '(nothing)'} — neither `push` nor "
                            f"`pull_request`, so nothing automatic ever runs it")
            continue
        # Round-6 F5: keyed by step *name* alone, a dishonest step named `build` in one
        # job suppressed an honest step of the same name in another — and unnamed steps
        # collide by construction, since they are all `step #1`, `step #2`, ...
        broken = set()
        for job_name, step_name, gated, message in gate_step_problems(
                workflow, required, only):
            for target in gated:
                rejected.setdefault(target, []).append(message)
            broken.add((workflow.name, job_name, step_name))
        for job_name, _job, step_name, step in steps(workflow):
            if (workflow.name, job_name, step_name) in broken:
                continue
            for line in run_commands(step["run"]):
                for target in MAKE_CALL_RE.findall(line):
                    invoked.setdefault(target, []).append(
                        f"{workflow.name}: job '{job_name}': step '{step_name}'")
    return invoked, rejected


def pr_only_declaration_problems(root):
    """A PR-only declaration that names something which is not a gate is dead text."""
    problems = []
    required = review_round_prerequisites(root)
    declared = pr_only_gates(root)
    for target in sorted(declared):
        if target not in required:
            problems.append(
                f"Makefile: PR_ONLY_GATES names {target!r}, which is not a prerequisite "
                f"of `review-round` — the exemption may only be spent on a real gate. "
                f"review-round runs {sorted(required)}")
    # Round-6 F6: the exemption's narrowness was social — declaring every gate PR-only
    # was accepted with no diagnostic, and a direct push to the default branch would
    # then run no gates at all. An exemption that can cover everything is not one.
    if required and declared >= required:
        problems.append(
            f"Makefile: PR_ONLY_GATES declares every gate `review-round` runs "
            f"({sorted(required)}) as PR-only, so a push to the default branch would "
            f"run no gate at all. The exemption is for the gates that genuinely cannot "
            f"run on a push event; at least one gate must remain unconditional")
    return problems


# ── WAIVERS.md ──────────────────────────────────────────────────────────────

# `WAIVED: <fingerprint> — <reason> (YYYY-MM-DD)`, anchored at both ends. build-process.md
# §4 gives a finding two possible ends: a fix with a regression test, or one line here.
WAIVER_RE = re.compile(r"^WAIVED:\s*(\S+)\s+—\s+\S.*\((\d{4}-\d{2}-\d{2})\)$")


def parse_waivers(root=None, text=None):
    """Return ({fingerprint: line}, [problems]).

    D-010 follow-up item 2. check.py's parser had no end anchor, so a line whose real
    tail was prose still matched on an incidental `(2026-08-11)` in the middle; the
    parity test's parser did have one, so the two disagreed about which findings were
    waived — and a line that matched neither simply vanished, waiving nothing, with no
    diagnostic anywhere. It bit during the D-010 PR: a waiver transcribed verbatim from
    the Architect's text stopped parsing and the gate reported "no marker" instead of
    "WAIVERS.md line 23 is unparseable".

    A line that opens with `WAIVED:` and does not parse is now a problem the caller must
    surface. Silence is what made it a defect.
    """
    if text is None:
        path = pathlib.Path(root) / "WAIVERS.md"
        if not path.exists():
            return {}, []
        text = path.read_text(encoding="utf-8")

    waivers, problems = {}, []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("WAIVED:"):
            continue
        m = WAIVER_RE.match(line)
        if m:
            # Round-6 F8: two lines waiving one fingerprint used to collapse silently to
            # whichever came last, so a superseded reason could sit in the file reading
            # as current.
            if m.group(1) in waivers:
                problems.append(
                    f"WAIVERS.md:{lineno}: duplicate waiver for {m.group(1)!r} — one "
                    f"fingerprint, one line (build-process.md §4); an earlier line for "
                    f"the same fingerprint is silently superseded")
            waivers[m.group(1)] = line
            continue
        hint = ""
        if re.search(r"^WAIVED:\s*\S+\s+[-–]\s", line):
            hint = (" — the separator after the fingerprint must be an em dash (—), "
                    "not a hyphen or en dash")
        elif not re.search(r"\(\d{4}-\d{2}-\d{2}\)$", line):
            hint = (" — the line must END with the date in parentheses, "
                    "(YYYY-MM-DD); a date earlier in the sentence does not count")
        problems.append(
            f"WAIVERS.md:{lineno}: unparseable waiver — expected "
            f"`WAIVED: <fingerprint> — <reason> (YYYY-MM-DD)`{hint}. This line waives "
            f"nothing as written: {line[:120]}{'…' if len(line) > 120 else ''}")
    return waivers, problems


# ── working-tree binding for the run report ─────────────────────────────────

def git_head(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 — an empty sha is red downstream, by design
        return ""


def _porcelain_paths(root):
    """Paths git reports as differing from HEAD, ignoring what .gitignore ignores.

    `--porcelain=v1 -z` emits `XY <path>\\0`, and for a rename or copy a second
    `\\0<original>` follows. Returns [(status, path)] sorted, or None if git failed.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "-uall", "-z"],
            capture_output=True, text=True, check=True)
    except Exception:  # noqa: BLE001
        return None
    fields = [f for f in out.stdout.split("\0") if f]
    entries, i = [], 0
    while i < len(fields):
        field = fields[i]
        if len(field) < 3:
            i += 1
            continue
        status, path = field[:2], field[3:]
        entries.append((status, path))
        if status[0] in "RC" or status[1] in "RC":
            i += 1  # the original path of a rename/copy
        i += 1
    return sorted(entries)


def tree_fingerprint(root):
    """A fingerprint of the *working tree*, not just of HEAD.

    Round-5 shipped the run report bound to `git rev-parse HEAD` and recorded the gap
    as deliberately open: edit a file after `make test` and the report still matched
    HEAD, so the gate graded a tree that no longer existed. Since gate machinery,
    product code and the registry are all read by `check.py` from the working tree,
    that is exactly the window in which a red run gets edited to green without the
    tests being re-run.

    HEAD, plus every path git reports as dirty, plus the content hash of each — so a
    clean checkout costs one `git status` and a dirty tree costs one hash per changed
    file. Ignored paths (the run report itself, `matrix.json`, `.venv`, caches) are not
    reported by `git status` and so cannot make the fingerprint chase its own tail.
    """
    root = pathlib.Path(root)
    head = git_head(root)
    entries = _porcelain_paths(root)
    if not head or entries is None:
        return ""
    digest = hashlib.sha256()
    digest.update(head.encode())
    for status, rel in entries:
        digest.update(b"\0" + status.encode() + b" " + rel.encode() + b"\0")
        path = root / rel
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest()
                          if path.is_file() else b"<absent>")
        except OSError:
            digest.update(b"<unreadable>")
    return "sha256:" + digest.hexdigest()
