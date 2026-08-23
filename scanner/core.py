"""Scanner core — module registry, dispatch, and the scan report (§S1, review3 §M1/§V4/§V5).

The one hard security rule (SEC-SCAN-NOEXEC, review3 §M1): the Hub-side scan path
executes NOTHING from the scanned project. Every check is classified `static`
(file/manifest/AST reading — runs here) or `executing` (install/build/tsc/test —
runs only in a disposable sandbox off the Hub, Phase 2). This module and every
scanner module import no process-execution machinery; a T1 test greps for it.

Mockup-first: modules are plain objects with four callables (§S1 interface):
    detect(root) -> bool
    checks(root) -> [CheckResult]           # static checks, run now
    sandbox_checks(root) -> [SandboxSpec]   # executing checks, EMITTED not run
    wizard_questions(root) -> [WizardQuestion]
    manifest_fragment(root, answers) -> dict  # merged into the ONE manifest (§V5)

Multiple modules may match one project (monorepo = service + static + offline
component); their outputs merge into one report and ONE manifest, never several
Sites (§V5). Fallback modules (`dockerfile`, `static`) run only when no framework
module matched (§V4) — an existing Dockerfile is validated input, never a bypass.

The common core suite (`core.*`, `modules.fallbacks.common_checks`) is composed
into every report by `scan()` here, once per scan over the SCAN root — modules
never call it themselves (D-010). A module may supersede a core result only by
emitting the same id; absence is impossible, so a Django report can no longer be
silently missing `core.secret-scan`.
"""
from dataclasses import dataclass, field
from pathlib import Path

# Bumped to 2 on 2026-08-16, when D-012 left Phase 1 (Joseph's cap decision): a
# stored report's MEANING changed — `acceptance` and `declared_test_material` left
# the schema. Phase 4 Task 3 re-lands those fields as OPTIONAL (omitted when
# None / empty, the same as_dict rule as `refused_paths`). SCHEMA_VERSION stays 2:
# a parked-era v2 row has no `acceptance`, so the restored grant route cannot
# open a blocker it does not name (fail-closed, R8-2's safe direction). v1 is
# still refused by preflight before any check is read.
SCHEMA_VERSION = 2

# Report tiers (§5.3). `pending_sandbox` marks an executing check honestly deferred.
TIERS = ("blocker", "warning", "advice", "ok", "pending_sandbox")

# The tiers an operator reads a REFUSAL from, and therefore the only tiers a check may
# vouch from when a module takes a file out of `core.symlinked-files` (R12-ARCH-1's rule,
# R13-ARCH-A's home for it).
#
# HERE, BESIDE `TIERS`, because it is a property OF the taxonomy and not a detail of the
# guard that consumes it. As a bare tuple two hundred lines down it read like a filter
# somebody happened to need: nothing said it was a subset of `TIERS`, nothing would have
# noticed if a tier were renamed underneath it, and the next reader met the fact in the
# middle of an error message. The subset property is asserted in
# tests/test_scanner_core.py, which is a sentence a tuple in a function's neighbourhood
# cannot say.
#
# WHY THESE TWO. Every refusal this repo emits is a warning — `core.symlinked-files`,
# `node-ts.symlinked-files` — for a stated reason: the survey below it is INCOMPLETE, and
# the operator has to know that before trusting the report. `blocker` is included because
# a future refusal that blocks is louder, not quieter. `advice` and `ok` are excluded
# because a file listed there is a fact nobody is being told, and `pending_sandbox` is
# excluded because it is a check that has not run yet — it cannot have refused anything.
ANNOUNCEMENT_TIERS = ("blocker", "warning")


@dataclass
class CheckResult:
    id: str                 # stable slug, e.g. "django.debug-hardcoded"
    tier: str               # one of TIERS
    title: str
    detail: str = ""
    fix_hint: str = ""      # §6.6 voice: what / why it matters / exact fix
    execution: str = "static"
    # Round 7 (R7-1) / Phase 4 Task 3 re-land. The smallest structured contract
    # that lets the wizard gate on a check without parsing its prose:
    # `{"questions": [confirm id, …], "blocking_only_declared": bool}`.
    #
    #   questions                 the confirm ids whose `True` accepts every
    #                             declaration this check labelled findings under
    #   blocking_only_declared    True when accepting them all leaves NOTHING
    #                             blocking; False when a real blocker (a [proof]
    #                             line, a .env file, an undeclared heuristic) is
    #                             also present, and then no answer clears it
    #
    # A check with nothing to accept leaves this None and `as_dict` OMITS the
    # key — a repo that declares nothing serializes as it did before the field
    # existed. Scan-time tier does not drop; the wizard owns the grant (D-012r).
    acceptance: dict = None
    # R12-A1: the repo-relative POSIX paths this check tells the operator were NOT READ.
    # Machine-readable, next to the sentence that says it in words — because the
    # sentence is for a person and the guard in `scan` needs a fact.
    #
    # It exists because the guard used to read the prose. `detail` is a report line: it
    # quotes repo-controlled text through `repr`, it truncates, it pluralizes, it caps a
    # list at ten and appends "… and 3 more". Substring-matching a path against that is
    # not a check, it is a coincidence detector, and it was defeated in both directions
    # inside one round — `src/metrics.tsx` vouching for `src/metrics.ts` (a passing
    # scan with the refusal named nowhere), and a legal committed link called
    # `src/metri\cs.ts` crashing every scan of the repository that carries it, because
    # the module printed the name through `repr` and the guard compared the raw one.
    #
    # OMITTED FROM `as_dict` WHEN EMPTY, which is most checks and every report on a tree
    # with no committed links: a report that had nothing to say about refusals is
    # byte-identical to the one this field did not exist for. That is what keeps the
    # recorded demo artifacts, the sim fixtures and every stored `scan_report` where they
    # are — and it is why SCHEMA_VERSION does not move. A schema bump means a stored
    # report's MEANING changed (R8-2, and the D-012 bump above is the precedent); this is
    # additive, and absent means "no refusals", which is what absent meant before.
    refused_paths: list = field(default_factory=list)

    def as_dict(self):
        out = {"id": self.id, "tier": self.tier, "title": self.title,
               "detail": self.detail, "fix_hint": self.fix_hint,
               "execution": self.execution}
        if self.acceptance is not None:
            out["acceptance"] = self.acceptance
        if self.refused_paths:
            out["refused_paths"] = list(self.refused_paths)
        return out


@dataclass
class SandboxSpec:
    """An executing check, emitted as a job spec for the Phase-2 sandbox runner.
    The scan report carries these as tier=pending_sandbox — never run on the Hub."""

    id: str
    command: list            # argv list (never a shell string — §4.5)
    cwd: str = "."
    why: str = ""

    def as_result(self):
        return CheckResult(
            id=self.id, tier="pending_sandbox", execution="executing",
            title=f"[sandbox] {self.id}",
            detail=f"Runs off-Hub (review3 §M1): {' '.join(self.command)}",
            fix_hint=self.why,
        )


@dataclass
class WizardQuestion:
    id: str
    prompt: str
    kind: str = "text"       # text | choice | bool | number | secret
    default: object = None
    choices: list = field(default_factory=list)

    def as_dict(self):
        return {"id": self.id, "prompt": self.prompt, "kind": self.kind,
                "default": self.default, "choices": self.choices}


# ── Registry (§V4 precedence: framework modules first, fallbacks last) ──────────

_FRAMEWORK_MODULES = []
_FALLBACK_MODULES = []

# Core ids a module is allowed to supersede, declared by the module as
# `supersedes = frozenset({...})`. A module that omits it supersedes nothing.
#
# D-010 follow-up item 1: same-id supersession is the designed mechanism and it is
# also the way to silently weaken a blocker — a module can replace `core.secret-scan`
# with an `ok` result, the invariant test checks presence and uniqueness rather than
# tier, and the replaced entry leaves no trace in the report. The only watcher was code
# review, and `scanner/modules/` was not on the sensitive-path human-merge list. Making
# the set explicit does not stop a determined author; it makes the attempt a one-line
# declaration in the diff, next to a test that freezes the union, instead of a change of
# tier buried in a check body.
_DEFAULT_SUPERSEDES = frozenset()


def repo_relative(root, path):
    r"""`path` as a repo-relative POSIX string, or None when it is not under `root`.

    R13-ARCH-B: ONE conversion. "The walked absolute path in, the report's spelling out"
    is the seam the R12-A1 bypasses lived on — a module refuses `root/src/metrics.ts`, the
    report carries `src/metrics.ts`, and the guard compares the two — and it was written
    three times: in `node_ts._Survey.refused_relative_paths`, in `fallbacks`' core refusal
    line, and in the guard below. Only the first and the third were ever pinned against
    each other, so the middle copy agreed by inspection, which is the state every drift in
    this repo has started from.

    HERE RATHER THAN IN `fallbacks`, where the other containment primitive (`escapes_root`)
    lives, and the reason is import direction: `fallbacks` and `node_ts` both already
    import from this module, while this module imports `fallbacks` only INSIDE `scan`, to
    keep the registry free of an import cycle. A helper in `fallbacks` would make that
    function-scoped import load-bearing for the guard as well.

    `as_posix()` IS A NO-OP ON THIS PLATFORM, and R13-REM-1 is the correction: an earlier
    version of this paragraph said `str()` and `as_posix()` "differ on a name a repository
    can legally commit", and cited S3's backslash for it. That is false here.
    `Path.relative_to` returns a `PosixPath`, whose `__str__` and `as_posix` are the same
    string for every filename, backslashes included — so on POSIX no input distinguishes
    them and no test can. Swapping this call for `str()` passed all 867 tests, which is
    how the claim was caught: a sentence about a guard, in the module that holds the
    guard, asserting a property nothing checks.

    The call stays, and the honest reason is smaller than the one it replaces: it DECLARES
    the spelling. This function's contract is "a POSIX string", the value is compared
    against POSIX spellings and stored in JSON a browser reads, and a reader should not
    have to know that `str()` happens to coincide on the one platform the Hub runs on. On
    a `PureWindowsPath` the two do differ — `src\a.ts` against `src/a.ts` — which is what
    the declaration is a declaration OF, and
    `tests/test_scanner_core.py::test_issue_r13_rem_1_*` pins that semantics with pure
    paths, on any host, and says in its own docstring that it is documenting the reason
    for the call rather than observing this platform.

    WHAT ACTUALLY DEFENDS THE ONE-CONVERSION PROPERTY is not a spelling test at all: it is
    `…_the_producers_call_the_shared_helper`, which patches this function in both producer
    modules and asserts both conversions came through it. Three copies that agree today
    are three copies; one function is one function.

    NONE RATHER THAN A RAISE OR AN ABSOLUTE STRING. Every caller's answer to "this path is
    not in the repository" is the same — keep it out of the report — but they say it
    differently: the two producers drop the entry (a stored report that names this
    machine's `/tmp` is a leak of the host's layout), and the guard turns it into the
    refusal that tells the module its spelling is wrong.
    """
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return None


def module_supersedes(module):
    return frozenset(getattr(module, "supersedes", _DEFAULT_SUPERSEDES))


def module_refused_paths(module, root):
    r"""The repo-controlled paths `module` reports refusing, or none (R10-A3).

    OPTIONAL, and absent means "this module names no refusals of its own", which is
    true of every module but `node-ts` today: `fallbacks` and `django` read through the
    shared walk and the shared `read_contained`, whose refusals ARE the core check's
    list, so there is nothing for them to declare and nothing to subtract.

    A module that declares one is saying "I have already told the operator about these
    files, in my own words" — and `scan` takes it at its word by dropping them from
    `core.symlinked-files`. That is the one-fact-one-line rule, and it is subtractive on
    the FILE rather than on the check, which is why it is not spelled as supersession:
    `core.symlinked-files` fires for every module's escapes and for reads no module
    makes, so replacing it whole would delete refusals nothing else reports.

    ── THE CONTRACT (R11-A2), which used to be stated nowhere ──────────────────

    Both halves are enforced by `_refused_paths_problem` below, at scan time, and both
    were fail-open before it existed.

    1. THE SPELLING IS THE WALKED ONE: a path under the SCAN ROOT, joined from it, the
       way `node_ts._iter_sources` yields it — `root / "packages/server/src/metrics.ts"`.
       NOT `path.resolve()`. The subtraction downstream is `Path` set membership against
       what the core walk found, and the core walk found the walked spelling; a resolved
       one matches nothing, subtracts nothing, and the file is reported twice — by core
       and by the module — which is precisely the defect R10-A3 was filed to fix,
       reopened by a one-word edit and visible in no test. Measured: `core.symlinked-
       files` and the module's own line both naming `.env`, warning count 4 on a tree
       with three things wrong with it.

    2. THE MODULE MUST HAVE ANNOUNCED IT, and R12-A1/R12-ARCH-1 between them fixed what
       that means: every path returned here must appear in the `refused_paths` LIST of a
       BLOCKER- OR WARNING-TIER check in the finished report. Not in anybody's prose (the
       R12-A1 half), and not on an `ok` line either (the R12-ARCH-1 half). The hook's
       justification is "I have already told the operator" — a module that returns a path
       and reports it nowhere deletes core's refusal line for that file and leaves NO
       trace, and a module that lists it on a check reading "everything looks fine" has
       deleted the same line and told the same nobody.

       "TOLD THE OPERATOR" IS ALSO NOW TRUE OF THE FIELD ITSELF. When the guard moved off
       `detail`, the thing it checked became a machine value rendered on no screen — the
       claim in this docstring outlived its evidence by one round. `CheckBody` in
       `frontend/src/Readiness.jsx` renders `refused_paths` under the check that carries
       it ("Did not read:", then the paths), so the fact the guard accepts as an
       announcement is the fact the operator reads. The tier rule and the rendering are
       two halves of one sentence: it has to be said, and it has to be said where a
       refusal is read.

    WHY A FIELD AND NOT THE SENTENCE (R12-A1). The first version of this guard read
    `detail`, which is a REPORT LINE: it quotes repo-controlled text through `repr`, it
    truncates at 80 characters, it caps a list and appends "… and 3 more". Matching a
    path against that is a coincidence detector, and it was defeated in both directions
    inside one round, on trees anybody can commit:

      * SUBSTRING — `rel in details` is unanchored, so a module refusing `src/metrics.ts`
        while its line named the sibling `src/metrics.tsx` passed. Measured: the scan
        returned green, `core.symlinked-files` named only the `.tsx`, and the refused
        file appeared in no check at all;
      * `repr` — this module family names refused paths through `_quote_pattern`, which
        is `repr`. A committed symlink called `src/metri\cs.ts` is legal on every
        filesystem this runs on, and its printed form escapes the backslash — so the raw
        spelling was not in the detail and `scan()` RAISED, falsely accusing the module.
        One committed file, every scan of that repository dead. Measured against the live
        `node-ts` module;
      * SUPERSESSION — the guard ran on what each module EMITTED, before supersession
        resolved. A second module superseding the same core id replaced the check that
        carried the naming, and the guard had already been satisfied by the check that
        was thrown away. Measured: `core.symlinked-files` surviving as `ok` "Nothing was
        refused", with two escaping files named nowhere.

    The remedy for the first two is that the fact and the sentence are different things:
    `CheckResult.refused_paths` is the fact, `detail` is the sentence, and only the fact
    is compared — by set membership, not by looking for one string inside another. The
    remedy for the third is that the comparison happens against the SURVIVING report,
    after supersession, plus `register`'s refusal to let two modules supersede one id.

    DESIGNED SO AN HONEST MODULE CANNOT TRIP IT, which is the property that decides
    whether a gate like this is worth having: a module that reports its refusals in a
    check — which it must, or the operator is not told — passes by construction, at any
    path length, in any tier, whatever characters the filesystem allowed in the name.
    There is no tolerance to tune, because there is nothing approximate left.

    It is still not proof that the module's SENTENCE is a good one — nothing mechanical
    can be — but "the file appears in this module's own report" is the claim the
    subtraction rests on, and it is now that claim that is checked.
    """
    hook = getattr(module, "refused_paths", None)
    return list(hook(root)) if hook is not None else []


# R13-ARCH-A: the rule moved up to `ANNOUNCEMENT_TIERS`, beside `TIERS`, where it is a
# property of the taxonomy rather than a filter this guard happens to want. The old name
# stays as an alias because it is what the refusal message and two tests call it, and
# renaming a constant in the same commit that moves it is two changes wearing one diff.
_REFUSAL_LOUD_TIERS = ANNOUNCEMENT_TIERS


def _refused_paths_problem(module, root, refused, reported):
    """The R11-A2/R12-A1 contract, as a sentence to raise or None.

    `reported` is the set of repo-relative POSIX paths the SURVIVING report ANNOUNCES —
    the `CheckResult.refused_paths` of every blocker- or warning-tier check in the
    finished list, after supersession has replaced what it replaces. See
    `module_refused_paths` for why each of those words is load-bearing.
    """
    root = Path(root)
    for raw in refused:
        path = Path(raw)
        rel = repo_relative(root, path)
        if rel is None:
            return (
                f"module {module.name!r} declares a refusal of {str(path)!r}, which is "
                f"outside the scan root {str(root)!r}. `refused_paths` returns the "
                f"WALKED spelling — the scan root joined with the repo-relative path, "
                f"which is what the core walk found and what the subtraction matches "
                f"against. A resolved path matches nothing, so the file is reported "
                f"twice: once by `core.symlinked-files` and once by this module")
        if rel not in reported:
            return (
                f"module {module.name!r} declares a refusal of {rel!r} and no check in "
                f"the finished report lists it in `refused_paths`. Declaring a refusal "
                f"drops that file from `core.symlinked-files`, on the module\'s word "
                f"that it has already told the operator about it — so a file nothing "
                f"then reports is a refusal the operator is told about by nobody. Put "
                f"the repo-relative POSIX path in the `refused_paths` of the check that "
                f"announces it (the detail is the sentence; this is the fact), or leave "
                f"the file in the core suite\'s list — and that check has to be one the "
                f"operator reads a refusal from ({' or '.join(_REFUSAL_LOUD_TIERS)}), "
                f"because a path listed on an `ok` line is a fact nobody is being told. "
                f"Announced by the surviving report: {sorted(reported) or 'nothing'}")
    return None


def register(module, fallback=False):
    # Item 8: the per-module invariant row is keyed by name, so two modules sharing one
    # would have collapsed into a single row and the second would have been checked by
    # nothing.
    existing = {m.name for m in _FRAMEWORK_MODULES} | {m.name for m in _FALLBACK_MODULES}
    if module.name in existing:
        raise ValueError(
            f"a scanner module named {module.name!r} is already registered — module "
            f"names key the report, the registry invariant and the demo records, and "
            f"a duplicate silently hides one of the two")
    # R12-A1 (S4): two modules may not supersede the same core id. Supersession replaces
    # an entry IN PLACE, so with two claimants the report shows whichever module ran
    # last — an ordering nothing declares and no test reads — and the other module's
    # result is gone with no trace. That is bad enough for `core.lockfile`; for
    # `core.symlinked-files` it is a refusal channel one module can quietly close over
    # another, which is how a file that WAS reported stops being reported while the
    # module that reported it still believes it did.
    #
    # Refused at registration rather than at scan time, for `supersedes`' own reason:
    # it is a declaration in a class body, so the collision is visible in the diff that
    # creates it and in the import that loads it, rather than on the one tree where both
    # modules happen to match.
    declared = module_supersedes(module)
    for other in _FRAMEWORK_MODULES + _FALLBACK_MODULES:
        shared = declared & module_supersedes(other)
        if shared:
            raise ValueError(
                f"scanner modules {other.name!r} and {module.name!r} both declare "
                f"`supersedes` over {sorted(shared)} — a core result can only be "
                f"replaced once, so on a tree both match the report shows whichever ran "
                f"last and the other's is deleted without trace. One module owns a core "
                f"id, or neither does")
    (_FALLBACK_MODULES if fallback else _FRAMEWORK_MODULES).append(module)
    return module


def registered_modules():
    return list(_FRAMEWORK_MODULES), list(_FALLBACK_MODULES)


def detect_modules(root):
    """§V4: every matching framework module runs; fallbacks only when none match."""
    matched = [m for m in _FRAMEWORK_MODULES if m.detect(root)]
    if matched:
        return matched
    return [m for m in _FALLBACK_MODULES if m.detect(root)]


def scan(root):
    """Run all matching modules' STATIC checks; emit executing checks as specs.

    Composition (D-010): when any module matches, the common core suite runs here
    exactly once over the scan root and leads the report — no module composes it.
    Supersession: a module result whose id is already in the suite REPLACES that
    entry in place (node-ts re-deriving `core.lockfile` is the precedent); an
    unknown `core.*` id is a ValueError, never a silent append.

    Returns the ScanReport dict (schema_version'd per §D8) that is stored on
    Project.scan_report and rendered by UI + CLI alike.
    """
    from . import modules  # noqa: F401 — importing registers the modules

    mods = detect_modules(root)
    checks, questions, sandbox = [], [], []
    # Per-module, and in `mods` order: `scan` narrows the core suite on what these say,
    # then checks each module's word against its own checks (R11-A2).
    refused_by_module = []
    manifest = {
        "schema_version": SCHEMA_VERSION,
        # §V5 component list — ONE Site: one service + optional static route +
        # optional jobs (+ jobs_image, §N7) + volumes (§N5).
        "components": {"service": None, "static_route": None, "jobs": []},
        "jobs_image": None,
        "volumes": [],
        "deploy_strategy": "blue_green",       # §N1 default; modules may set recreate
        "exposure": "public",                  # §M4; wizard may set mesh_only
        "healthz": {                           # §N2 pinned contract fields
            # warmup seeds None so a module's per-class default (node-ts: 600s,
            # §N2) survives the first-set-wins merge; the pipeline applies 120s
            # only when no module set one.
            "liveness_path": None, "readiness_path": None,
            "warmup_timeout_s": None, "data_staleness_threshold": None,
        },
    }
    core_suite = []
    if mods:
        from . import declarations
        from .modules.fallbacks import common_checks

        # D-012 re-land (Phase 4 Task 3 / D-055 / C1). ONE READ of deployhub.yaml
        # (R7-13): two reads of a file the scanned repo owns can disagree inside
        # one scan, and the halves that disagree are the labelled bucket and the
        # confirm that is supposed to authorize it. scan() loads, threads the
        # Declarations into the suite, extends questions via confirm_questions
        # (R7-14), and drafts declared_test_material. The scanner does not drop
        # tier; wizard acceptance is the grant (D-012r).
        declared = declarations.load(root)
        # R10-A3: the matched modules are asked what they have already refused BEFORE
        # the core suite composes its refusal line, so that line can leave those files
        # to the module that names them better. Asked here rather than collected from
        # the loop below because the core suite is built first — and it is built first
        # so that supersession can replace an entry in place, which is the property the
        # report's stable check ordering rests on.
        refused_by_module = [module_refused_paths(m, root) for m in mods]
        refused_elsewhere = [p for paths in refused_by_module for p in paths]
        core_suite = common_checks(
            root, declared=declared, refused_elsewhere=refused_elsewhere)
        questions.extend(declarations.confirm_questions(declared))
        if declared.accepted:
            # The DRAFT list — what the repo asked for. What gets frozen is the
            # answer-derived list built by wizard.materialize (R7-A §5).
            manifest["declared_test_material"] = [
                {"path": d.path, "reason": d.reason} for d in declared.accepted]
    core_pos = {c.id: i for i, c in enumerate(core_suite)}

    for m in mods:
        allowed = module_supersedes(m)
        for c in m.checks(root):
            if c.id in core_pos:
                if c.id not in allowed:
                    raise ValueError(
                        f"module {m.name!r} supersedes core check {c.id!r} without "
                        f"declaring it: add it to the module's `supersedes` frozenset "
                        f"(declared: {sorted(allowed) or 'nothing'}). Superseding a "
                        f"core result replaces it outright, tier included, so it is a "
                        f"deliberate, reviewable act — not something a check body "
                        f"does in passing")
                core_suite[core_pos[c.id]] = c    # supersession: same id, position kept
            elif c.id.startswith("core."):
                raise ValueError(
                    f"module {m.name!r} emits unknown core check id {c.id!r}")
            else:
                checks.append(c)
        sandbox.extend(m.sandbox_checks(root))
        questions.extend(m.wizard_questions(root))
        _deep_merge(manifest, m.manifest_fragment(root, answers=None))
    checks = core_suite + checks
    checks.extend(spec.as_result() for spec in sandbox)

    # R12-A1 (S4): the refusal guard runs HERE, against the report that survived.
    #
    # It used to run inside the loop above, on what each module EMITTED — before
    # supersession replaced anything. A module could therefore satisfy the guard with a
    # check that a later module then replaced, and the refusal it had subtracted from
    # `core.symlinked-files` was reported by nothing that reached the operator. The
    # module's word is checked against what the operator will actually see, which is the
    # only list that means anything, and that list only exists once every module has run.
    #
    # `strict=True`: the two sequences are built from `mods` a dozen lines apart, and a
    # length that stopped matching would silently pair a module with another module's
    # refusals — the fail-open this whole guard is about, one level up.
    reported = {rel for c in checks if c.tier in _REFUSAL_LOUD_TIERS
                for rel in c.refused_paths}
    for m, refused in zip(mods, refused_by_module, strict=True):
        problem = _refused_paths_problem(m, root, refused, reported)
        if problem is not None:
            raise ValueError(problem)

    tiers = {t: sum(1 for c in checks if c.tier == t) for t in TIERS}
    return {
        "schema_version": SCHEMA_VERSION,
        "modules": [m.name for m in mods],
        "checks": [c.as_dict() for c in checks],
        "sandbox_jobs": [
            {"id": s.id, "command": s.command, "cwd": s.cwd, "why": s.why}
            for s in sandbox
        ],
        "wizard_questions": [q.as_dict() for q in questions],
        "manifest_draft": manifest,
        "summary": tiers,
    }


def _deep_merge(base, fragment):
    """Later modules fill gaps; scalar conflicts prefer the STRICTER value where we
    know what stricter means (deploy_strategy: recreate wins), else first-set wins."""
    if not fragment:
        return base
    for key, val in fragment.items():
        if key == "deploy_strategy":
            if "recreate" in (val, base.get(key)):
                base[key] = "recreate"           # §N1: recreate is mandatory-if-flagged
            continue
        cur = base.get(key)
        if isinstance(cur, dict) and isinstance(val, dict):
            _deep_merge(cur, val)
        elif isinstance(cur, list) and isinstance(val, list):
            cur.extend(v for v in val if v not in cur)
        elif cur in (None, [], {}):
            base[key] = val
    return base
