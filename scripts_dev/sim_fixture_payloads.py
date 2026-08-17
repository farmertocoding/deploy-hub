"""Regenerate the payloads `frontend/src/sim.js` claims came from a real run.

    python scripts_dev/sim_fixture_payloads.py                 # both payloads, JSON
    python scripts_dev/sim_fixture_payloads.py --project-2     # just the messy one

WHY THIS EXISTS, and it is R8's finding one turn further on. `sim_fixture_repos.py` is
committed because "a fixture nobody can re-derive is a UI nobody reviewed", and it makes
the TREES re-derivable. It does not make the PAYLOADS re-derivable: sim.js's own comment
says they came from `ReadinessSerializer(...).data` run over those trees and points at
"the commit that regenerated sim.js for the exact harness", which is a harness that lives
in a commit message. Half a derivation is a derivation nobody runs.

R9-Q2 is what that costs. The two suites are green on either side of a boundary neither
of them crosses: the python suite asserts what the scanner emits, the node suite asserts
what the screens render out of sim.js, and NOTHING asserts the two describe the same
scanner. A coordinated rename — `core.secret-scan` to `core.secrets`, say, changed in
`fallbacks.py` and in the python tests together — leaves both suites green while sim.js
goes on showing an id the product no longer emits. The demo becomes fiction by drift
rather than by anybody's decision, which is exactly how the round-8 fixtures got there.

SCOPE, stated because it is narrower than "regenerate sim.js". This emits the READINESS
payload — the scan plus `ReadinessSerializer`, which is `MESSY_REPORT` and the clean
project's equivalent. sim.js also carries `MESSY_WIZARD` (from `wizard.views._state`) and
a materialized manifest; both need a live database and a `Site` row with answers on it,
which is a test-database harness rather than a script, and neither carries the
SCANNER-emitted ids that the drift gate is about. They are the next step, not this one.

`tests/test_simulation.py::test_issue_r9_q2_*` reads this module and compares the result
against sim.js. ADVISORY today (build-process §4's diff-coverage precedent: advisory
first, blocking after) — see that test for the one line that flips it.
"""
import argparse
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# The timestamps sim.js carries. They are not derivable from a scan — the fixture trees
# are written fresh every time this runs — so they are inputs here, spelled once, and
# the drift gate ignores them for the same reason.
SCANNED_AT = {
    "project-1": "2026-08-09T10:00:00Z",
    "project-2": "2026-08-09T09:30:00Z",
}

# The readiness payload's list keys, in tier order. NOT the tier names for two of the
# four — `ReadinessSerializer` pluralizes `blocker`/`warning` and does not pluralize
# `advice`/`pending_sandbox`. Spelled once, here, because reading the payload with the
# tier names silently yields the two lists whose names happen to collide and an empty
# result for the other two, which reads exactly like "no blockers".
PAYLOAD_KEYS = ("blockers", "warnings", "advice", "pending_sandbox")


def _setup_django():
    """Enough Django for the serializers, and nothing more — no database is touched.

    `ReadinessSerializer` is a plain `serializers.Serializer` over a dict, so this needs
    the app registry and DRF's settings and no connection. Importing it is the point:
    the payload has to come from the class the API actually returns, or this harness is
    a second implementation of the response shape and drifts exactly like the fixture it
    is here to check.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def readiness_payload(root, scanned_at):
    """`GET /api/v1/projects/<id>/readiness/`'s body for a scan of `root`.

    The tier grouping is `wizard.views.ReadinessView.get`'s, and the serializer is its
    serializer. What this cannot borrow is the view itself, which needs a `Project` row.
    """
    _setup_django()
    from scanner import core as scanner_core
    from wizard.views import ReadinessSerializer

    report = scanner_core.scan(root)
    checks = report.get("checks", [])
    return json.loads(json.dumps(ReadinessSerializer({
        "scanned_at": scanned_at,
        "modules": report.get("modules", []),
        "summary": report.get("summary", {}),
        "blockers": [c for c in checks if c.get("tier") == "blocker"],
        "warnings": [c for c in checks if c.get("tier") == "warning"],
        "advice": [c for c in checks if c.get("tier") == "advice"],
        "pending_sandbox": [c for c in checks if c.get("tier") == "pending_sandbox"],
    }).data))


def build_trees(base="/tmp"):
    """Write the fixture repos and return `{project key: root}`.

    `base` is a parameter so a test can build them under `tmp_path` instead of `/tmp`:
    two runs racing on one hard-coded path is a flake, and `sim_fixture_repos.write`
    starts by `rmtree`-ing its target.
    """
    if str(REPO / "scripts_dev") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts_dev"))
    import sim_fixture_repos as fixtures

    base = pathlib.Path(base)
    return {
        "project-1": fixtures.write(base / "cleanrepo", fixtures.CLEAN),
        "project-2": fixtures.write(base / "messyrepo", fixtures.MESSY),
    }


def payloads(base="/tmp", keys=None):
    """`{project key: readiness payload}`, freshly scanned off freshly written trees."""
    roots = build_trees(base)
    return {key: readiness_payload(root, SCANNED_AT[key])
            for key, root in roots.items() if keys is None or key in keys}


def check_tiers(payload):
    """`{check id: tier}` for every check the payload NAMES.

    The `ok` tier is deliberately absent from both sides: the readiness payload groups
    only the four tiers the screens render, so an `ok` check appears in `summary` as a
    count and nowhere else. This is what the drift gate compares.
    """
    return {check["id"]: check["tier"]
            for key in PAYLOAD_KEYS for check in payload.get(key, [])}


def main(argv=None):
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--base", default="/tmp",
                      help="where to write the fixture trees (default: /tmp)")
    args.add_argument("--project-1", dest="keys", action="append_const",
                      const="project-1")
    args.add_argument("--project-2", dest="keys", action="append_const",
                      const="project-2")
    opts = args.parse_args(argv)
    print(json.dumps(payloads(opts.base, opts.keys), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
