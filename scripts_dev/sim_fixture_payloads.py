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
from typing import NamedTuple

REPO = pathlib.Path(__file__).resolve().parent.parent

import django  # noqa: E402 — sys.path/settings bootstrap precedes framework imports

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
from django.apps import apps as _apps  # noqa: E402

if not _apps.ready:
    django.setup()

from django.test.runner import DiscoverRunner  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402

sys.path.insert(0, str(REPO / "scripts_dev"))          # this file's own directory
import sim_fixture_repos as fixture_repos  # noqa: E402

UTC = datetime.timezone.utc
# The dates the fixtures are stitched with. Hand-written, and the sim.js header says so.
CLEAN_AT = datetime.datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
MESSY_AT = datetime.datetime(2026, 8, 9, 9, 30, tzinfo=UTC)
EDGE_AT = datetime.datetime(2026, 8, 9, 11, 15, tzinfo=UTC)
RESCAN_AT = datetime.datetime(2026, 8, 12, 7, 20, tzinfo=UTC)


class _Tree(NamedTuple):
    """How one report-carrying sim.js payload's tree is built, and when it was scanned.

    `files` and `links` are the dicts in `sim_fixture_repos`, REFERENCED rather than
    named by string, and it is worth being exact about what that buys — an earlier
    version of this docstring claimed a guard it does not have.

    WHAT ACTUALLY FIRES, both of them:

      * a referenced dict RENAMED OR REMOVED in `sim_fixture_repos` is an
        `AttributeError` while this module is being imported, which takes the harness
        and the drift gate down together. Named by string it would have been a fixture
        tree that quietly resolved to nothing.
      * a payload added to `frontend/src/sim.js` with no entry HERE is caught on the
        sim.js side, by
        `tests/test_simulation.py::test_issue_r10_a2_the_gate_covers_every_report_payload_sim_js_carries`
        — every `*_REPORT` constant the file declares must appear in the inventory, with
        `UNSCANNED_REPORT` the one exemption and exempted by name.

    WHAT DOES NOT, stated so the next reader does not take the reference for a
    completeness check: a NEW, unreferenced dict added to `sim_fixture_repos` and not
    added here fires nothing at all. Nothing scans that module for trees, and a tree with
    no sim.js payload has nothing to compare against — it becomes a finding the moment
    someone gives it a payload, via the second mechanism above.
    """

    directory: str
    files: dict
    links: dict
    scanned_at: datetime.datetime


# ── the tree inventory, spelled once (R10-A2) ─────────────────────────────────
#
# KEYED BY THE sim.js CONSTANT, like everything else this file emits. It used to be
# keyed `project-1` / `project-2` in a table that listed exactly those two, so the
# blocking drift gate could not see EDGE_REPORT or RESCANNED_REPORT at all — which is
# the precise gap R10-Q2 shipped through: five stale edge payloads, past a gate that was
# green because it was not looking.
#
# `scanned_at` is the DATETIME, not a second copy of it as an ISO string. The strings
# that used to live here restated CLEAN_AT and MESSY_AT, three lines below their own
# definitions, and `DateTimeField.to_representation` renders the datetime to exactly
# that string anyway — so the copy bought nothing and could disagree.
SIM_REPORT_TREES = {
    "CLEAN_REPORT": _Tree("cleanrepo", fixture_repos.CLEAN, None, CLEAN_AT),
    "MESSY_REPORT": _Tree("messyrepo", fixture_repos.MESSY, None, MESSY_AT),
    "EDGE_REPORT": _Tree("edgerepo", fixture_repos.EDGE, fixture_repos.EDGE_LINKS,
                         EDGE_AT),
    "RESCANNED_REPORT": _Tree("cleanrepo-rescanned", fixture_repos.CLEAN_RESCANNED,
                              None, RESCAN_AT),
}

# Written beside them and carrying no payload of its own: what the edge tree's committed
# symlink points AT. Without it that link is BROKEN rather than ESCAPING, which is a
# different refusal with different wording, so the containment finding under test would
# quietly stop being the one the fixture claims.
SIM_SUPPORT_TREES = {"edge-neighbour": fixture_repos.NEIGHBOUR}

# UNSCANNED_REPORT is deliberately absent: `orders-api` has never been scanned, its
# payload carries no checks and no tree exists to scan. A drift gate entry for it would
# compare {} with {} forever.


def tree_path(key, base="/tmp"):
    """Where `key`'s tree lives — one derivation, so no caller types `/tmp/cleanrepo`."""
    return str(pathlib.Path(base) / SIM_REPORT_TREES[key].directory)


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

    takko = project("takko", "takko", tree_path("CLEAN_REPORT"), CLEAN_AT)
    legacy = project("legacy-shop", "legacy-shop", tree_path("MESSY_REPORT"), MESSY_AT)
    edge = project("atlas-edge", "atlas-edge", tree_path("EDGE_REPORT"), EDGE_AT)
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

    # R10-A6: the keys of `out` ARE the constant names in sim.js, so that regenerating
    # is a splice and not a translation step. These four were `*_PROJECT_ROW` against
    # sim.js's `*_PROJECT` — the one family that did not line up, in the one place where
    # a name that does not line up means a payload silently not spliced.
    #
    # EVERY PROJECT ROW IS CAPTURED BEFORE THE POST THAT SCREEN MAKES, because the row is
    # what the operator is looking at when they press the button. takko/prod is three
    # manifests old, so the fourth is the one the sim returns; atlas-edge has none, so its
    # ack-confirmed POST returns v1. Both numbers are generated, neither is edited — the
    # round-8 defect class was a fixture whose numbers were typed to agree with each other.
    for _ in range(3):
        materialize(prod)
    out["CLEAN_PROJECT"] = project_row(takko)
    out["MESSY_PROJECT"] = project_row(legacy)
    out["EDGE_PROJECT"] = project_row(edge)
    out["UNSCANNED_PROJECT"] = project_row(orders)

    # ── the STALE timeline, played FIRST and at v3 (R10-UX-F3) ───────────────
    #
    # sim.js's `live` and `stale` are two different stories about the same site, and the
    # stale one has to be observed BEFORE the live one's POST because its whole content
    # is what the site looks like when a materialize did NOT happen: the tree moved, the
    # POST was refused, and a refusal creates no manifest.
    #
    # Captured after the live POST — which is where this used to sit — the post-refusal
    # row showed v4 with `manifest_current: false`, so the screen the operator converges
    # on after a 409 read as though the refused request had incremented the version. The
    # correct row is v3 (the three materializes above, and no fourth) with
    # `manifest_current: false`, because the report under it moved.
    clean_report, clean_at = takko.scan_report, takko.scanned_at
    takko.scan_report = scanner_core.scan(tree_path("RESCANNED_REPORT"))
    takko.scanned_at = RESCAN_AT
    takko.save(update_fields=["scan_report", "scanned_at"])

    out["STALE_REFUSAL_409"] = post_manifest(prod)
    out["RESCANNED_REPORT"] = readiness(takko)
    out["RESCANNED_WIZARD"] = wizard(prod)
    out["RESCANNED_PROJECT"] = project_row(takko)

    # …and back to the report the LIVE state serves, so the POSTs below are the ones
    # those screens really make. The rewind is a fixture-stitching step and is stated
    # rather than hidden: nothing above it is re-captured, and every payload below is a
    # real run against the clean tree's report, which is what `?sim=live` shows.
    takko.scan_report, takko.scanned_at = clean_report, clean_at
    takko.save(update_fields=["scan_report", "scanned_at"])

    # ── the LIVE timeline's POSTs, and what the screen looks like after them ──
    #
    # R10-UX-F2: the `*_AFTER` rows are the missing half. `live` answered every request
    # from one table, so the re-read a 201 triggers returned the PRE-POST row forever:
    # "Manifest v1 created." beside "no manifest yet", permanently, on the one screen
    # whose whole point is the ack checkbox changing the server's answer. These are the
    # rows the same `ProjectListView` derivation produces one materialize later.
    out["CLEAN_MANIFEST"] = post_manifest(prod)
    out["CLEAN_PROJECT_AFTER"] = project_row(takko)
    out["REFUSAL_409"] = post_manifest(shop)
    out["STAGING_409"] = post_manifest(staging)
    # The warnings gate, both answers, same site, in the order the operator meets them.
    out["WARNINGS_409"] = post_manifest(atlas, confirm_warnings=False)
    out["EDGE_MANIFEST"] = post_manifest(atlas, confirm_warnings=True)
    out["EDGE_PROJECT_AFTER"] = project_row(edge)

    # What a materialize does NOT change, asserted rather than assumed — this is the
    # claim sim.js's post-201 state rests on when it goes on serving the same report and
    # wizard payloads after the POST. A materialize freezes the manifest and applies the
    # answers to the Site; it does not re-scan, and `_state` reads `preflight`, which
    # reads the report. If that ever stops being true, the fixture needs a `*_AFTER`
    # for these too and this line is what says so.
    assert wizard(atlas) == out["EDGE_WIZARD"], "a materialize moved the wizard state"
    assert readiness(edge) == out["EDGE_REPORT"], "a materialize moved the report"
    assert readiness(takko) == out["CLEAN_REPORT"], "a materialize moved the report"

    # ── the answer that clears "Answers needed" (R10-UX-F4) ──────────────────
    #
    # takko/staging is the site nobody has configured: its only refusal is
    # `answers_missing`, the gate reads "Answers needed", and until now no sim state had
    # a payload for what happens when the operator types the domain and presses Save.
    # `live`'s PATCH returned `{}` and the refetch returned the same unanswered state
    # forever, so the one refusal the form itself clears had no clearing path in any
    # reviewable state. This is `_state(staging)` after a real `set_answers`.
    #
    # LAST, because it changes the site: every capture above sees staging unanswered,
    # which is what `STAGING_WIZARD` and `STAGING_409` are.
    wizard_service.set_answers(staging, {"site.domain": "staging.takko.market"})
    out["STAGING_WIZARD_ANSWERED"] = wizard(staging)
    # …and what the enabled button then does, because leaving `STAGING_409` behind an
    # answered wizard would be a fixture saying `can_materialize: true` and refusing for
    # `answers_missing` in the same breath.
    out["STAGING_MANIFEST"] = post_manifest(staging)
    out["CLEAN_PROJECT_ANSWERED"] = project_row(takko)
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        # R10-A7, and it is the `mutation_gate.py` precedent from this same round. This
        # generator takes no arguments and never has: it prints EVERY payload, because
        # the drift they are checked against is a whole-file property and a partial
        # regeneration is how half of sim.js gets left behind. The remediation line the
        # drift gate printed said `--project-2`, an option this `main` has never
        # accepted and would have silently ignored — so somebody following the
        # instruction would have got a full run, believed they had scoped it, and been
        # right by accident. Refusing is the only reading of an argument that cannot be
        # wrong. Exit 2: declining to run, not a verdict about the fixtures.
        print(f"sim_fixture_payloads: refusing to run with arguments {argv} — this "
              f"generator takes none and prints every sim.js payload. The keys of its "
              f"output are the constant names in frontend/src/sim.js; splice all of "
              f"them, because the drift gate reads the file as a whole. Run "
              f"`python scripts_dev/sim_fixture_payloads.py` with no arguments.",
              file=sys.stderr)
        return 2
    setup_test_environment()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    try:
        json.dump(build(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    finally:
        runner.teardown_databases(old_config)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# ── DB-free drift-gate entry points (merged from r9-backend-remedy) ─────────────
#
# The section above builds every sim.js payload through a test database. The drift
# gate (tests/test_simulation.py) needs only the READINESS payloads, per fresh scans of
# freshly written trees, with no database at all — so it imports these instead of
# build(). Two entry points, one module, because a second harness file would be a second
# copy of the derivation, which is the defect class this file exists to close.
#
# R10-A2: and the trees they scan are `SIM_REPORT_TREES` above — the same inventory the
# DB half builds its projects from. This section used to carry its own two-entry table
# hardcoding project-1 and project-2, which is why the blocking gate never looked at
# EDGE_REPORT or RESCANNED_REPORT.

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
    """Write every fixture repo and return `{sim.js constant: root}`.

    `base` is a parameter so a test can build them under `tmp_path` instead of `/tmp`:
    two runs racing on one hard-coded path is a flake, and `sim_fixture_repos.write`
    starts by `rmtree`-ing its target.

    The support trees go first. They carry no payload, and the edge tree's committed
    symlink resolves INTO one of them — written second, the link would still point at
    nothing at the moment the scan reads it, and a broken link is a different refusal
    from an escaping one.
    """
    base = pathlib.Path(base)
    for directory, files in SIM_SUPPORT_TREES.items():
        fixture_repos.write(base / directory, files)
    return {key: fixture_repos.write(base / tree.directory, tree.files, tree.links)
            for key, tree in SIM_REPORT_TREES.items()}


def payloads(base="/tmp", keys=None):
    """`{sim.js constant: readiness payload}`, freshly scanned off freshly written trees.

    The keys are the sim.js constant names, so the gate that consumes this can name the
    payload it is comparing rather than translating an id into one.
    """
    roots = build_trees(base)
    return {key: readiness_payload(root, SIM_REPORT_TREES[key].scanned_at)
            for key, root in roots.items() if keys is None or key in keys}


def check_tiers(payload):
    """`{check id: tier}` for every check the payload NAMES.

    The `ok` tier is deliberately absent from both sides: the readiness payload groups
    only the four tiers the screens render, so an `ok` check appears in `summary` as a
    count and nowhere else. This is what the drift gate compares.
    """
    return {check["id"]: check["tier"]
            for key in PAYLOAD_KEYS for check in payload.get(key, [])}

