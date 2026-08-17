"""Generate every payload in frontend/src/sim.js from a real run, as JSON on stdout.

Not part of the product — a dev-only driver, the same shape as `ws_reconnect_demo.py`
and the companion to `sim_fixture_repos.py`, which builds the trees this scans. It is
committed for the reason r8 filed and round 9 filed again: a fixture nobody can
re-derive is a UI nobody reviewed, and a payload typed by hand is a screen reviewed
against a fiction. Until this file existed the trees were reproducible and the harness
over them lived in a commit message, which is one copy-and-paste away from not being
reproducible at all.

    python scripts_dev/sim_fixture_repos.py
    python scripts_dev/sim_fixture_payloads.py > /tmp/fixtures.json

The keys of that object are the constant names in `frontend/src/sim.js`; each value is
spliced in as JSON (`json.dumps(indent=2)`) rather than retyped. To check the committed
file has not drifted, regenerate and compare the constants as the UI sees them — through
`SIM_FIXTURES`, not by reading the source — normalising only the wall-clock values the
sim.js header says are hand-written (`changed_at`, `created_at`).

WHAT IS REAL HERE AND WHAT IS NOT. Everything below runs the product's own code:
`scanner.core.scan` over the fixture trees, `wizard.service.set_answers` for the
answers, `wizard.views._state` for the wizard payloads, `wizard.materialize.materialize`
for the manifests and the refusals, and the three serializers for the response bodies.
The project/site ids, names, slugs and `scanned_at` stamps are chosen here, because the
sim's fixtures have to stitch together across four projects and a database sequence is
not a stable name for anything. Creation ORDER is therefore load-bearing: the ids it
produces (projects 1-4, sites 1-5) are the ids sim.js routes on.
"""
import datetime
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

import django  # noqa: E402 — sys.path/settings bootstrap precedes framework imports

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
from django.apps import apps as _apps  # noqa: E402

if not _apps.ready:
    django.setup()

from django.test.runner import DiscoverRunner  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402

UTC = datetime.timezone.utc
# The dates the fixtures are stitched with. Hand-written, and the sim.js header says so.
CLEAN_AT = datetime.datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
MESSY_AT = datetime.datetime(2026, 8, 9, 9, 30, tzinfo=UTC)
EDGE_AT = datetime.datetime(2026, 8, 9, 11, 15, tzinfo=UTC)
RESCAN_AT = datetime.datetime(2026, 8, 12, 7, 20, tzinfo=UTC)


def as_json(data):
    """Through JSON, so what is printed is exactly what the API would put on the wire."""
    return json.loads(json.dumps(data))


def build():
    from core.models import Project, Site
    from scanner import core as scanner_core
    from wizard import service as wizard_service
    from wizard.materialize import MaterializeRefused, materialize, report_hash
    from wizard.views import (
        ManifestSerializer,
        ProjectSummarySerializer,
        WizardStateSerializer,
        _state,
        readiness_body,
    )

    def readiness(project):
        """ReadinessView.get's body, against a project row rather than a request.

        R10-A5: `readiness_body` IS the view's body. This used to re-implement the tier
        grouping, which made the drift gate downstream compare sim.js against a second
        implementation of the endpoint rather than against the endpoint.
        """
        return as_json(readiness_body(project.scan_report, project.scanned_at))

    def wizard(site):
        return as_json(WizardStateSerializer(_state(site)).data)

    def project_row(project):
        """ProjectListView.get's row for one project — tiers, sites, manifest currency."""
        report = project.scan_report or {}
        checks = report.get("checks", [])
        current_hash = report_hash(report) if report else None
        sites = []
        for site in project.sites.all().order_by("pk"):
            latest = site.manifests.order_by("-version").first()
            sites.append({
                "id": site.pk, "name": site.name, "domain": site.domain,
                "latest_manifest_version": latest.version if latest else None,
                "manifest_current": (None if latest is None or current_hash is None
                                     else latest.scan_report_hash == current_hash),
            })
        return as_json(ProjectSummarySerializer({
            "id": project.pk, "name": project.name, "slug": project.slug,
            "scanned_at": project.scanned_at,
            "tiers": {t: sum(1 for c in checks if c.get("tier") == t)
                      for t in ("blocker", "warning", "advice", "pending_sandbox")},
            "sites": sites,
        }).data)

    def post_manifest(site, *, confirm_warnings=False):
        """ManifestView.post: the 201 body or the 409 body, whichever really happens."""
        try:
            manifest = materialize(site, confirm_warnings=confirm_warnings)
        except MaterializeRefused as refusal:
            return as_json(refusal.as_dict())
        return as_json(ManifestSerializer(manifest).data)

    def project(name, slug, path, scanned_at):
        return Project.objects.create(
            name=name, slug=slug, source_kind=Project.Source.LOCAL_PATH,
            local_path=path,
            scan_report=scanner_core.scan(path) if scanned_at else {},
            scanned_at=scanned_at)

    out = {}

    takko = project("takko", "takko", "/tmp/cleanrepo", CLEAN_AT)
    legacy = project("legacy-shop", "legacy-shop", "/tmp/messyrepo", MESSY_AT)
    edge = project("atlas-edge", "atlas-edge", "/tmp/edgerepo", EDGE_AT)
    # Added and never scanned: the state `?sim=degraded` shows and `preflight` refuses
    # with `scan_required` before it reads anything else.
    orders = project("orders-api", "orders-api", "/tmp/not-scanned-yet", None)

    prod = Site.objects.create(project=takko, name="prod")          # site 1
    shop = Site.objects.create(project=legacy, name="prod")         # site 2
    atlas = Site.objects.create(project=edge, name="prod")          # site 3
    staging = Site.objects.create(project=takko, name="staging")    # site 4
    orders_site = Site.objects.create(project=orders, name="prod")  # site 5
    assert [s.pk for s in (prod, shop, atlas, staging, orders_site)] == [1, 2, 3, 4, 5]

    wizard_service.set_answers(prod, {"site.domain": "takko.market"})
    # A saved secret and an unanswered required question in one state: the screen shows
    # the secret's metadata ("set <date>; leave blank to keep") beside a missing domain.
    wizard_service.set_answers(shop, {
        "site.exposure": "public",
        "django.env.FIELD_ENCRYPTION_KEYS": "fixture-value-not-a-real-key",
    })
    wizard_service.set_answers(atlas, {"site.domain": "edge.atlas.market"})
    # staging is answered by nobody on purpose — that is round-9 item 3's whole screen.

    out["CLEAN_REPORT"] = readiness(takko)
    out["CLEAN_WIZARD"] = wizard(prod)
    out["STAGING_WIZARD"] = wizard(staging)
    out["MESSY_REPORT"] = readiness(legacy)
    out["MESSY_WIZARD"] = wizard(shop)
    out["EDGE_REPORT"] = readiness(edge)
    out["EDGE_WIZARD"] = wizard(atlas)
    out["UNSCANNED_REPORT"] = readiness(orders)
    out["UNSCANNED_WIZARD"] = wizard(orders_site)

    # EVERY PROJECT ROW IS CAPTURED BEFORE THE POST THAT SCREEN MAKES, because the row is
    # what the operator is looking at when they press the button. takko/prod is three
    # manifests old, so the fourth is the one the sim returns; atlas-edge has none, so its
    # ack-confirmed POST returns v1. Both numbers are generated, neither is edited — the
    # round-8 defect class was a fixture whose numbers were typed to agree with each other.
    for _ in range(3):
        materialize(prod)
    out["CLEAN_PROJECT_ROW"] = project_row(takko)
    out["MESSY_PROJECT_ROW"] = project_row(legacy)
    out["EDGE_PROJECT_ROW"] = project_row(edge)
    out["UNSCANNED_PROJECT_ROW"] = project_row(orders)

    out["CLEAN_MANIFEST"] = post_manifest(prod)
    out["REFUSAL_409"] = post_manifest(shop)
    out["STAGING_409"] = post_manifest(staging)
    # The warnings gate, both answers, same site, in the order the operator meets them.
    out["WARNINGS_409"] = post_manifest(atlas, confirm_warnings=False)
    out["EDGE_MANIFEST"] = post_manifest(atlas, confirm_warnings=True)

    # ── and then the tree moves under the operator ────────────────────────────
    # Same project, same site, same answers; a re-scan of the clean tree with one live
    # -format Stripe key committed to it. The refusal and the three payloads the screen
    # must converge on after it all come from this one state.
    takko.scan_report = scanner_core.scan("/tmp/cleanrepo-rescanned")
    takko.scanned_at = RESCAN_AT
    takko.save(update_fields=["scan_report", "scanned_at"])

    out["STALE_REFUSAL_409"] = post_manifest(prod)
    out["RESCANNED_REPORT"] = readiness(takko)
    out["RESCANNED_WIZARD"] = wizard(prod)
    out["RESCANNED_PROJECT_ROW"] = project_row(takko)
    return out


def main():
    setup_test_environment()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    try:
        json.dump(build(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    finally:
        runner.teardown_databases(old_config)


if __name__ == "__main__":
    main()

# ── DB-free drift-gate entry points (merged from r9-backend-remedy) ─────────────
#
# The section above builds every sim.js payload through a test database. The drift
# gate (tests/test_simulation.py::test_issue_r9_q2_*) needs only the READINESS
# payloads, per fresh scans of freshly written trees, with no database at all — so it
# imports these instead of build(). Two entry points, one module, because a second
# harness file would be a second copy of the derivation, which is the defect class
# this file exists to close.

SCANNED_AT = {
    "project-1": "2026-08-09T10:00:00Z",
    "project-2": "2026-08-09T09:30:00Z",
}

# The readiness payload's list keys, in tier order. NOT the tier names for two of the
# four — `ReadinessSerializer` pluralizes `blocker`/`warning` and does not pluralize
# `advice`/`pending_sandbox` — so reading the payload with the tier names silently
# yields the two lists whose names happen to collide and an empty result for the other
# two, which reads exactly like "no blockers".
#
# R10-A5: IMPORTED rather than spelled. This was a third copy of a mapping the endpoint
# already owns, in the file whose entire job is proving that sim.js is what the endpoint
# returns.
from wizard.views import READINESS_KEYS as PAYLOAD_KEYS  # noqa: E402


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

    R10-A5: the body is `wizard.views.readiness_body`, which is what the view returns.
    What this cannot borrow is the VIEW, which needs a `Project` row and a database; the
    grouping and the serializer are no longer re-implemented to work around that.
    """
    _setup_django()
    from scanner import core as scanner_core
    from wizard.views import readiness_body

    return json.loads(json.dumps(
        readiness_body(scanner_core.scan(root), scanned_at)))


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

