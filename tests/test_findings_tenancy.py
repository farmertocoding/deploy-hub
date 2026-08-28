"""ZT-03: findings and alert state are unique per workspace.

What would make these fail: looking up or mutating findings by fingerprint
alone, so a transition in workspace A changes B.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from django.db import IntegrityError, connection, transaction

from core.findings import ack, finding
from core.models import AlertState, Finding, Workspace, default_workspace
from monitor.antinoise import observe

REPO = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {
    ".git", ".venv", ".venv-scaffold", ".worktrees", "node_modules",
    "frontend", "mutants", "staticfiles", "__pycache__", "tests",
    "conformance", "migrations",
}

pytestmark = pytest.mark.django_db

COPY = dict(
    severity="p1",
    entity="site:shop.example.com",
    title="Site is down",
    body="why it matters",
    fix_action="restart",
)


def test_two_workspaces_file_the_same_fingerprint_independently():
    alpha = Workspace.objects.create(name="Alpha", slug="alpha-find")
    beta = Workspace.objects.create(name="Beta", slug="beta-find")
    a = finding("uptime", "shared-fp", workspace=alpha, **COPY)
    b = finding("uptime", "shared-fp", workspace=beta, **COPY)
    assert a.pk != b.pk
    assert Finding.objects.filter(fingerprint="shared-fp").count() == 2
    ack(a)
    b.refresh_from_db()
    assert b.state == Finding.State.OPEN
    assert Finding.objects.get(pk=a.pk).state == Finding.State.ACKED


def test_finding_requires_workspace():
    with pytest.raises(TypeError):
        finding("uptime", "no-ws", **COPY)


def test_alert_state_is_per_workspace():
    alpha = Workspace.objects.create(name="Alpha", slug="alpha-alert")
    beta = Workspace.objects.create(name="Beta", slug="beta-alert")
    observe("site-down:x", False, workspace=alpha)
    observe("site-down:x", False, workspace=alpha)
    observe("site-down:x", False, workspace=alpha)
    assert Finding.objects.filter(workspace=alpha, fingerprint="site-down:x").exists()
    assert not Finding.objects.filter(workspace=beta, fingerprint="site-down:x").exists()
    observe("site-down:x", True, workspace=beta)
    assert AlertState.objects.filter(workspace=alpha, fingerprint="site-down:x").count() == 1
    assert AlertState.objects.filter(workspace=beta, fingerprint="site-down:x").count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    connection.vendor == "sqlite",
    reason="SQLite cannot serialize concurrent writers of the same finding row",
)
def test_concurrent_filing_is_idempotent_per_workspace():
    from django.db import connections
    from django.db.utils import OperationalError

    workspace = default_workspace()

    def _file(_n):
        connections.close_all()
        last = None
        for _ in range(8):
            try:
                return finding("uptime", "race-fp", workspace=workspace, **COPY).pk
            except (IntegrityError, OperationalError) as exc:
                last = exc
        raise last

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(_file, range(2)))
    assert ids[0] == ids[1]
    assert Finding.objects.filter(workspace=workspace, fingerprint="race-fp").count() == 1
    connection.close()
    assert transaction.atomic


def test_group_p2_does_not_return_another_workspace_finding():
    """Push-log lookup by fingerprint alone mixes tenants.

    What would make this fail: Finding.objects.filter(fingerprint=fp).first()
    so workspace B's row is delivered for workspace A's event.
    """
    from django.utils import timezone

    from monitor.antinoise import _record_push, group_p2

    alpha = Workspace.objects.create(name="Alpha", slug="alpha-p2")
    beta = Workspace.objects.create(name="Beta", slug="beta-p2")
    p2 = {**COPY, "severity": Finding.Severity.P2}
    a = finding("monitor.alerts", "stale:shared", workspace=alpha, **p2)
    b = finding("monitor.alerts", "stale:shared", workspace=beta, **p2)
    now = timezone.now()
    _record_push(a, now)
    _record_push(b, now)
    pushes = group_p2(window=600, mark=False)
    returned = {row.pk for group in pushes for row in group["findings"]}
    assert a.pk in returned
    assert b.pk in returned
    by_ws = {row.workspace_id: row.pk for group in pushes for row in group["findings"]}
    assert by_ws[alpha.pk] == a.pk
    assert by_ws[beta.pk] == b.pk


def test_cert_refusal_lookup_is_workspace_scoped():
    """Wizard site rows must not pick up another tenant's finding_id.

    What would make this fail: Finding.objects.filter(fingerprint__in=...) with
    no workspace, so a forged row in A paints B's site.
    """
    from wizard.views import _open_attack_states, _open_cert_refusals

    alpha = Workspace.objects.create(name="Alpha", slug="alpha-wiz")
    beta = Workspace.objects.create(name="Beta", slug="beta-wiz")
    from core.models import Project, Site

    project = Project.objects.create(workspace=beta, name="b", slug="b-wiz")
    site = Site.objects.create(project=project, name="b-site", exposure="mesh_only")
    real = finding(
        "test", f"unproxied-cert:{site.pk}", workspace=beta, **COPY,
    )
    forged = finding(
        "test", f"unproxied-cert:{site.pk}", workspace=alpha, **COPY,
    )
    attack_forged = finding(
        "test", f"attack-playbook-engaged:{site.dns_zone_id or 0}",
        workspace=alpha, **COPY,
    )
    refusals = _open_cert_refusals([site])
    assert refusals[f"unproxied-cert:{site.pk}"].pk == real.pk
    assert refusals[f"unproxied-cert:{site.pk}"].pk != forged.pk
    attacks = _open_attack_states([site])
    if site.dns_zone_id:
        assert attacks[f"attack-playbook-engaged:{site.dns_zone_id}"].workspace_id == beta.pk
        assert attack_forged.workspace_id == alpha.pk


def test_raise_alert_requires_workspace():
    from monitor.alerts import raise_alert

    with pytest.raises(TypeError, match="workspace"):
        raise_alert(
            "feed-data-stale",
            "feed:x",
            fingerprint="stale:need-ws",
            title=COPY["title"],
            body=COPY["body"],
            fix_action=COPY["fix_action"],
        )


def test_finding_and_alert_state_have_no_orm_workspace_default():
    from django.db import IntegrityError
    from django.db.models.fields import NOT_PROVIDED

    field = Finding._meta.get_field("workspace")
    assert field.default is NOT_PROVIDED
    alert_field = AlertState._meta.get_field("workspace")
    assert alert_field.default is NOT_PROVIDED
    with pytest.raises((IntegrityError, TypeError, ValueError)):
        Finding.objects.create(
            source_engine="t", severity="p1", entity="e", title="t",
            body="b", fix_action="f", fingerprint="no-ws-default",
        )


def _finding_manager_call(node):
    """True when `node` is Finding/AlertState.objects.filter/get/get_or_create()."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in {"filter", "get", "get_or_create"}:
        return False
    objects = node.func.value
    if not isinstance(objects, ast.Attribute) or objects.attr != "objects":
        return False
    return (
        isinstance(objects.value, ast.Name)
        and objects.value.id in {"Finding", "AlertState"}
    )


def test_production_fingerprint_lookups_include_workspace():
    """Production fingerprint lookups must also key workspace.

    What would make this fail: Finding.objects.filter(fingerprint=fp).first()
    so a forged row in A paints or resolves B.
    """
    offenders = []
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO)
        if set(rel.parts) & _SKIP_DIRS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not _finding_manager_call(node):
                continue
            keys = {kw.arg for kw in node.keywords if kw.arg}
            fp_keys = {key for key in keys if key.startswith("fingerprint")}
            ws_keys = {
                key for key in keys
                if key == "workspace" or key.startswith("workspace_id")
            }
            if fp_keys and not ws_keys:
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], (
        "Finding/AlertState fingerprint lookups must include workspace: "
        + ", ".join(offenders)
    )


def test_retract_does_not_resolve_another_workspace_finding():
    from core.models import Project, Site
    from scaling.evaluator import KIND, _retract

    alpha = Workspace.objects.create(name="Alpha", slug="alpha-retract")
    beta = Workspace.objects.create(name="Beta", slug="beta-retract")
    project = Project.objects.create(workspace=beta, name="b", slug="b-retract")
    site = Site.objects.create(project=project, name="b-site", exposure="mesh_only")
    fp = f"{KIND}:{site.pk}"
    forged = finding("test", fp, workspace=alpha, **COPY)
    real = finding("test", fp, workspace=beta, **COPY)
    _retract(site)
    forged.refresh_from_db()
    real.refresh_from_db()
    assert forged.state == Finding.State.OPEN
    assert real.state == Finding.State.RESOLVED


def test_apply_edge_owner_does_not_resolve_another_workspace_finding():
    from core.models import Project, Site
    from provision.adopt import AMBIGUOUS_FP, apply_edge_owner

    alpha = Workspace.objects.create(name="Alpha", slug="alpha-edge")
    beta = Workspace.objects.create(name="Beta", slug="beta-edge")
    project = Project.objects.create(workspace=beta, name="b", slug="b-edge")
    site = Site.objects.create(project=project, name="b-site", exposure="mesh_only")
    fp = AMBIGUOUS_FP.format(site_id=site.pk)
    forged = finding("adopt", fp, workspace=alpha, **COPY)
    real = finding("adopt", fp, workspace=beta, **COPY)
    apply_edge_owner(site, "caddy")
    forged.refresh_from_db()
    real.refresh_from_db()
    assert forged.state == Finding.State.OPEN
    assert real.state == Finding.State.RESOLVED


def test_router_advisor_lookup_is_workspace_scoped():
    from core.models import NetworkZone, Target
    from monitor.router_advisor import _open_or_acked

    alpha = Workspace.objects.create(name="Alpha", slug="alpha-router")
    beta = Workspace.objects.create(name="Beta", slug="beta-router")
    zone = NetworkZone.objects.create(workspace=beta, name="z", slug="z-router")
    target = Target.objects.create(zone=zone, host="router.example.test")
    fp = f"router-forwarded:{target.pk}"
    forged = finding("router_advisor", fp, workspace=alpha, **COPY)
    real = finding("router_advisor", fp, workspace=beta, **COPY)
    row = _open_or_acked(target)
    assert row.pk == real.pk
    assert row.pk != forged.pk


def test_partner_webhook_disabled_is_workspace_scoped():
    from core.models import Partner
    from core.partner_webhooks import _is_disabled

    alpha = Workspace.objects.create(name="Alpha", slug="alpha-hook")
    beta = Workspace.objects.create(name="Beta", slug="beta-hook")
    partner = Partner.objects.create(workspace=beta, name="p", slug="p-hook")
    fp = f"hub-egress-degraded:partner:{partner.pk}"
    finding("partner_webhooks", fp, workspace=alpha, **COPY)
    assert _is_disabled(partner) is False
    finding("partner_webhooks", fp, workspace=beta, **COPY)
    assert _is_disabled(partner) is True
