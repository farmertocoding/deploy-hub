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


def register(module, fallback=False):
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
            "liveness_path": None, "readiness_path": None,
            "warmup_timeout_s": 120, "data_staleness_threshold": None,
        },
    }
    for m in mods:
        checks.extend(m.checks(root))
        sandbox.extend(m.sandbox_checks(root))
        questions.extend(m.wizard_questions(root))
        _deep_merge(manifest, m.manifest_fragment(root, answers=None))
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
