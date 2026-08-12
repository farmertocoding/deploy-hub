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

SCHEMA_VERSION = 1

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
    # Round 7 (R7-1, spec-r7-enforce-declaration-acceptance.md §2). The smallest
    # structured contract that lets the wizard gate on a check without parsing its
    # prose: `{"questions": [confirm id, …], "blocking_only_declared": bool}`.
    #
    #   questions                 the confirm ids whose `True` accepts every
    #                             declaration this check downgraded findings under
    #   blocking_only_declared    True when accepting them all leaves NOTHING blocking;
    #                             False when a real blocker (a [proof] line, a .env
    #                             file, an undeclared heuristic line) is also present,
    #                             and then no answer clears the check at all
    #
    # Deliberately the minimum: the §F2 per-finding array is a later, separate change.
    # A check with nothing to accept leaves this None and `as_dict` OMITS the key —
    # serializing `"acceptance": null` on every check of every repo would have moved
    # all five recorded demo artifacts to say nothing had changed.
    acceptance: dict = None

    def as_dict(self):
        data = {"id": self.id, "tier": self.tier, "title": self.title,
                "detail": self.detail, "fix_hint": self.fix_hint,
                "execution": self.execution}
        if self.acceptance is not None:
            data["acceptance"] = self.acceptance
        return data


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

        # Follow-up 2 (spec-declared-test-material.md §The report shows the claim): the
        # DOWNGRADE is the repo's claim, made in its own `deployhub.yaml` and printed in
        # the check detail; the ACCEPTANCE is the operator's, asked here and enforced by
        # the wizard, per §F5 action-tier friction. A repo that declares nothing adds
        # no question and no manifest key, so every report predating this feature is
        # unchanged byte for byte.
        #
        # ONE READ, and R7-13 is why the previous comment here ("parsed once; two
        # readers below") was worth fixing rather than deleting: it was false — the
        # suite loaded the file again for the check. Two reads of a file the SCANNED
        # REPO owns can disagree inside one scan (an edit landing between them, a
        # symlink swapped), and the halves that disagree are the downgrade and the
        # confirm that is supposed to authorize it.
        declared = declarations.load(root)
        core_suite = common_checks(root, declared)   # runs over the SCAN root, once
        # R7-14: the prompt copy, the slug scheme and the `_env_name` defense behind it
        # are rules about a declaration and live with the code that validated it. D-010
        # made this module the composer; composing is what it does here.
        questions.extend(declarations.confirm_questions(declared))
        if declared.accepted:
            # The DRAFT list — what the repo asked for, in declaration order. What gets
            # frozen into the manifest is the answer-derived list built by
            # `wizard.materialize` (R7-A §5); before round 7 this draft was frozen
            # verbatim, so the audit artifact asserted an acceptance nobody had given.
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
