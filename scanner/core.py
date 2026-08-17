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

# Bumped to 2 on 2026-08-16, when D-012 left Phase 1 (Joseph's cap decision,
# `claude/decision-2026-08-16-round-6-cap.md`): a stored report's MEANING changed —
# checks no longer carry an `acceptance` contract and the manifest draft no longer
# carries `declared_test_material`. R8-2 is the finding that says a meaning change
# without a version bump lets pre-change rows through the gate on the new code's
# reading of the old fields, so the bump lands with the change that earned it and
# `wizard.materialize.preflight` refuses anything that does not match.
SCHEMA_VERSION = 2

# Report tiers (§5.3). `pending_sandbox` marks an executing check honestly deferred.
TIERS = ("blocker", "warning", "advice", "ok", "pending_sandbox")


@dataclass
class CheckResult:
    id: str                 # stable slug, e.g. "django.debug-hardcoded"
    tier: str               # one of TIERS
    title: str
    detail: str = ""
    fix_hint: str = ""      # §6.6 voice: what / why it matters / exact fix
    execution: str = "static"
    # D-012 out of Phase 1 (2026-08-16): the `acceptance` field is GONE, not left
    # defaulting to None. It carried the confirm ids whose `True` cleared a blocker
    # this check had downgraded on the scanned repo's own say-so, and there is no
    # such downgrade and no such gate this phase. A dataclass field written by
    # nothing and read by nothing is R7-15's finding — the next reader assumes a
    # dead field on a security record is load-bearing — and here it would be worse
    # than dead: `wizard.materialize` used to open a blocker for it, so leaving the
    # field would leave the shape of a bypass lying in the report.

    def as_dict(self):
        return {"id": self.id, "tier": self.tier, "title": self.title,
                "detail": self.detail, "fix_hint": self.fix_hint,
                "execution": self.execution}


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


def module_supersedes(module):
    return frozenset(getattr(module, "supersedes", _DEFAULT_SUPERSEDES))


def module_refused_paths(module, root):
    """The repo-controlled paths `module` reports refusing, or none (R10-A3).

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

    2. THE MODULE MUST HAVE SAID SO: the path's repo-relative POSIX spelling appears in
       the `detail` of at least one check that same module emits from this scan. The
       hook's entire justification is "I have already told the operator, in my own
       words"; a module that returns a path and mentions it nowhere deletes core's
       refusal line for that file and leaves NO trace — no check names it, no count
       moves, and the operator's model of what the scan read is wrong with nothing on
       screen to correct it. Measured on a synthetic module: `core.symlinked-files` gone
       from the report entirely, and no line anywhere in its place.

    WHY THIS SHAPE AND NOT SUPERSESSION'S. `supersedes` is a declaration a module makes
    ONCE, in its class body, and the diff shows it. A refusal list is per-scan data, so
    the equivalent is a per-scan check — the module's own report is the declaration, and
    the guard is that the report actually contains it.

    DESIGNED SO AN HONEST MODULE CANNOT TRIP IT, which is the property that decides
    whether a gate like this is worth having:

      * the spelling rule is the one a walk produces by construction. A module would
        have to go out of its way — call `resolve()` — to break it, and that call is
        exactly the mistake being caught;
      * the naming rule tolerates BOUNDED text. Repo-controlled strings in a report are
        truncated (`node_ts._quote_pattern` cuts at 80 characters and appends
        `(truncated)`), so a deeply nested file is named by a prefix of its own path. A
        guard demanding the whole string would accuse the module that behaves most
        carefully. A prefix of `_REFUSAL_NAMED_PREFIX` characters counts, and that floor
        is well below any truncation limit a readable report could use — but ONLY in a
        `_REFUSAL_LOUD_TIERS` detail (F-2). A prefix names a directory rather than a
        file, so two siblings under a deep path share one; requiring the weaker match to
        appear where an operator reads refusals is what keeps a passing mention of
        `alpha.ts` from vouching for `beta.ts`.

    It is still not proof that the module's sentence is a GOOD one — nothing mechanical
    can be — but "the file appears in this module's own report" is the claim the
    subtraction rests on, and it is now checked rather than assumed.
    """
    hook = getattr(module, "refused_paths", None)
    return list(hook(root)) if hook is not None else []


# How much of a refused path's repo-relative spelling has to appear in the module's own
# detail. Full string first; this is the floor for the truncated case. Below any
# truncation limit a report could reasonably use (node-ts's is 80) and long enough that
# two different files sharing it would have to be siblings under a deep path.
_REFUSAL_NAMED_PREFIX = 60

# …and "siblings under a deep path" is not a hypothetical, which is F-2. Two files in one
# deep directory share their first 60 characters, so a line about `alpha.ts` satisfied the
# guard for `beta.ts` — and `beta.ts` then vanished from `core.symlinked-files` with
# nothing anywhere saying it was not read. The tolerance added to keep the guard honest
# was itself a way through it.
#
# The prefix now counts only in a WARNING-OR-WORSE detail. Every refusal this repo emits
# is a warning (`core.symlinked-files`, `node-ts.symlinked-files`) and for a stated
# reason — the survey below it is INCOMPLETE and the operator has to know that before
# trusting the report — so the weaker match is admitted only where an operator reads
# refusals from. A module that mentions a sibling in passing, in an `advice` or `ok` line,
# is no longer vouching for a file it never named.
#
# The EXACT spelling still counts in any tier, and that asymmetry is the point: a full
# path names one file and nothing else, so where it is said is a question of quality
# rather than of identity. A prefix names a directory, and a directory is not a file.
_REFUSAL_LOUD_TIERS = ("blocker", "warning")


def _refused_paths_problem(module, root, refused, emitted):
    """The R11-A2 contract, as a sentence to raise or None. See `module_refused_paths`."""
    root = Path(root)
    details = "\n".join(c.detail or "" for c in emitted)
    loud = "\n".join(c.detail or "" for c in emitted if c.tier in _REFUSAL_LOUD_TIERS)
    for raw in refused:
        path = Path(raw)
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            return (
                f"module {module.name!r} declares a refusal of {str(path)!r}, which is "
                f"outside the scan root {str(root)!r}. `refused_paths` returns the "
                f"WALKED spelling — the scan root joined with the repo-relative path, "
                f"which is what the core walk found and what the subtraction matches "
                f"against. A resolved path matches nothing, so the file is reported "
                f"twice: once by `core.symlinked-files` and once by this module")
        named = rel in details or (
            len(rel) > _REFUSAL_NAMED_PREFIX
            and rel[:_REFUSAL_NAMED_PREFIX] in loud)
        if not named:
            return (
                f"module {module.name!r} declares a refusal of {rel!r} and names it in "
                f"no check it emits. Declaring a refusal drops that file from "
                f"`core.symlinked-files`, on the module's word that it has already told "
                f"the operator about it — so a file nothing then mentions is a refusal "
                f"the operator is told about by nobody. Either report it in a check's "
                f"`detail`, or leave it in the core suite's list. (A path longer than "
                f"{_REFUSAL_NAMED_PREFIX} characters may be named by its first "
                f"{_REFUSAL_NAMED_PREFIX}, for reports that bound repo-controlled text "
                f"— but only in a {' or '.join(_REFUSAL_LOUD_TIERS)} check, because a "
                f"prefix names a directory and a sibling in an advice line is not this "
                f"file)")
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
        from .modules.fallbacks import common_checks

        # D-012 out of Phase 1 (2026-08-16, Joseph's cap decision). `scan` used to load
        # `deployhub.yaml` here, thread the parsed declarations into the suite, extend
        # `questions` with a confirm per accepted declaration and draft a
        # `declared_test_material` key into the manifest. All three are gone: the file
        # is not parsed by any live path this phase, nothing downgrades anything, and
        # the only trace of the file in a report is the `core.declaration-file` presence
        # notice the suite emits so a repo carrying one is told it is not honored.
        # `scanner/declarations.py` stays on master, parked and unit-tested, and returns
        # as its own phase behind a written threat model.
        #
        # R10-A3: the matched modules are asked what they have already refused BEFORE
        # the core suite composes its refusal line, so that line can leave those files
        # to the module that names them better. Asked here rather than collected from
        # the loop below because the core suite is built first — and it is built first
        # so that supersession can replace an entry in place, which is the property the
        # report's stable check ordering rests on.
        refused_by_module = [module_refused_paths(m, root) for m in mods]
        refused_elsewhere = [p for paths in refused_by_module for p in paths]
        core_suite = common_checks(root, refused_elsewhere)   # over the SCAN root, once
    core_pos = {c.id: i for i, c in enumerate(core_suite)}

    # `strict=True`: the two lists are built from `mods` a dozen lines apart, and a
    # length that stops matching would silently pair a module with another module's
    # refusals — which is the fail-open this whole guard is about, one level up.
    for m, refused in zip(mods, refused_by_module, strict=True):
        allowed = module_supersedes(m)
        # R11-A2: the module's checks are taken once and checked against what it said
        # it refused, BEFORE any of them reach the report. The core suite above was
        # already narrowed on this module's word; this is where the word is checked.
        emitted = list(m.checks(root))
        problem = _refused_paths_problem(m, root, refused, emitted)
        if problem is not None:
            raise ValueError(problem)
        for c in emitted:
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
