"""Attack playbook L5 + never-scale (D-057, C3, C4).

Named tests from docs/plan/phase-4-tasks.md Task 4. The playbook takes
EdgeProtection | None; edge_protection_for(zone) is the only constructor.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from test_cloudflare_adapter import FakeCloudflare

from core.models import Finding

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
DNS_TOKEN = "cf-dns-t1-playbook-token-not-a-credential"  # nosec B105
EDGE_TOKEN = "cf-edge-t1-playbook-token-not-a-credential"  # nosec B105
ATTACKER_IP = "203.0.113.9"
VERIFY = ("GET", "/user/tokens/verify")
PROBE = ("GET", "/zones?per_page=50")
SKIP_DIRS = {
    ".git", ".venv", ".venv-scaffold", ".worktrees", "node_modules",
    "frontend", "mutants", "staticfiles", "__pycache__",
}


@pytest.fixture(autouse=True)
def _reset_seams():
    from monitor.pager import reset_pager
    from providers.registry import reset_scope_cache

    reset_pager()
    reset_scope_cache()
    yield
    reset_pager()
    reset_scope_cache()


def _world(slug, *, dns_token=None, edge_token=None):
    from core.models import DnsAccount, DnsZone, NetworkZone, Project, Site, Target
    from vault import service as vault_service

    project = Project.objects.create(name=slug, slug=slug)
    net = NetworkZone.objects.create(name=f"nz-{slug}", slug=f"nz-{slug}")
    target = Target.objects.create(
        zone=net, host=f"{slug}.lan", ssh_key_ref=f"ssh-{slug}",
        status=Target.Status.READY,
    )
    account = DnsAccount.objects.create(provider="cloudflare", label=f"acct-{slug}")
    if dns_token is not None:
        ref = f"dns-{slug}"
        vault_service.put(
            kind="api_token", owner_type="dns_account", owner_id=ref,
            plaintext=dns_token.encode(),
        )
        account.dns_token_ref = ref
    if edge_token is not None:
        ref = f"edge-{slug}"
        vault_service.put(
            kind="api_token", owner_type="dns_account", owner_id=ref,
            plaintext=edge_token.encode(),
        )
        account.edge_token_ref = ref
    account.save()
    zone = DnsZone.objects.create(
        account=account, name=f"{slug}.example", provider_zone_id=f"zid-{slug}",
    )
    site = Site.objects.create(
        project=project, name=slug, domain=f"{slug}.example",
        dns_zone=zone, primary_target=target,
    )
    return site


def _plant_traffic(site, counts, *, now=None, ip=ATTACKER_IP):
    from core.models import TrafficStat

    now = (now or timezone.now()).replace(second=0, microsecond=0)
    for offset, requests in enumerate(reversed(list(counts))):
        TrafficStat.objects.create(
            site=site,
            bucket_start=now - timedelta(minutes=offset),
            granularity=TrafficStat.Granularity.MINUTE,
            requests=requests,
        )
    target = site.primary_target
    target.collect_payload = {
        "log_chunk": {"summary": {"top_ips": [[ip, int(counts[-1])]]}},
    }
    target.save(update_fields=["collect_payload"])


def _attack_shaped(site, *, ip=ATTACKER_IP):
    _plant_traffic(site, [10] * 20 + [8000], ip=ip)


def _scope_routes(zone):
    return {
        VERIFY: {"success": True, "result": {"id": "tok-1", "status": "active"}},
        PROBE: {
            "success": True,
            "result": [{"id": zone.provider_zone_id, "name": zone.name}],
        },
    }


def _http(monkeypatch, routes):
    import providers.cloudflare as cloudflare

    http = FakeCloudflare(routes)
    monkeypatch.setattr(cloudflare, "urlopen", http)
    return http


def _node_name(func):
    return getattr(func, "id", None) or getattr(func, "attr", None)


def _class_or_func_source(path, *, class_name=None, func_name=None):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if class_name and isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.get_source_segment(src, node) or ast.unparse(node)
        if func_name and isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment(src, node) or ast.unparse(node)
    return ""


def _attr_loads(source, name):
    """True when `source` reads `.name` (docstrings mentioning the field do not count)."""
    tree = ast.parse(source)
    return any(
        isinstance(node, ast.Attribute) and node.attr == name
        for node in ast.walk(tree)
    )


def _package_imports_name(package, needle):
    hits = []
    root = REPO / package
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(REPO)
        if set(rel.parts) & SKIP_DIRS:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if needle in alias.name.split("."):
                        hits.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if needle in module.split("."):
                    hits.append(f"{rel}:{node.lineno}")
                for alias in node.names:
                    if needle in alias.name.split("."):
                        hits.append(f"{rel}:{node.lineno}")
    return hits


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_edge_protection_for_is_the_only_constructor():
    """AST: CloudflareEdge(...) lives only in edge_protection_for (C3, D-057).

    What would make this fail: a playbook, deploy step, or view constructing
    CloudflareEdge directly and skipping the fail-closed edge-token wall.
    """
    from providers.cloudflare import CloudflareEdge
    from providers.registry import edge_protection_for

    src = (REPO / "providers" / "cloudflare.py").read_text(encoding="utf-8")
    assert "class CloudflareEdge" in src
    registry_src = (REPO / "providers" / "registry.py").read_text(encoding="utf-8")
    assert "CloudflareEdge(" in registry_src
    assert "def edge_protection_for" in registry_src

    allowed = {"providers/registry.py"}
    offenders = []
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO)
        if set(rel.parts) & SKIP_DIRS or str(rel) in allowed:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _node_name(node.func) == "CloudflareEdge":
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], offenders

    hits = _package_imports_name("deploys", "cloudflare")
    assert hits == [], f"deploys/ imports cloudflare: {hits}"
    assert edge_protection_for.__name__ == "edge_protection_for"
    assert issubclass(CloudflareEdge, object)


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_playbook_sets_under_attack_and_bans_ip():
    """z-score trip → set_security_level(under_attack) then ban_ip (L5).

    What would make this fail: notifying without flipping Under-Attack, or
    banning before the security level is set, or never calling ban_ip.
    """
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    site = _world("l5-ban")
    _attack_shaped(site)
    edge = FakeEdgeProtection()
    row = run(site, edge)
    assert row is not None
    zone = site.dns_zone
    assert edge.security_level[zone] == "under_attack"
    assert any(item[1] == ATTACKER_IP for item in edge.banned)
    mutating = [call[0] for call in edge.mutating_calls()]
    assert mutating[0] == "set_security_level"
    assert "ban_ip" in mutating
    assert mutating.index("set_security_level") < mutating.index("ban_ip")


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_playbook_without_edge_ref_notifies_only():
    """Absent edge ref → None → notify-only Finding, never a silent no-op (C3).

    What would make this fail: returning without filing, or pretending the
    edge acted when edge_protection_for returned None.
    """
    from monitor.attack_playbook import fingerprint_for, run
    from providers.registry import edge_protection_for
    from wizard.views import project_row_body

    site = _world("l5-none")
    _attack_shaped(site)
    assert site.dns_zone.account.edge_token_ref == ""
    assert edge_protection_for(site.dns_zone) is None
    row = run(site, None)
    assert row is not None
    assert row.fingerprint == fingerprint_for(site.dns_zone)
    blob = f"{row.title}\n{row.body}\n{row.fix_action}".lower()
    assert "notify-only" in blob or "notify only" in blob
    payload = project_row_body(site.project)["sites"][0]["attack_state"]
    assert payload is not None
    assert payload["finding_id"] == row.pk
    assert payload["mode"] == "notify_only"


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_playbook_run_twice_zero_mutating_calls():
    """Second pass records zero EdgeProtection mutations (D-018).

    What would make this fail: re-PATCHing Under-Attack or re-POSTing the
    same IP ban on every detector tick.
    """
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    site = _world("l5-twice")
    _attack_shaped(site)
    edge = FakeEdgeProtection()
    run(site, edge)
    first = list(edge.mutating_calls())
    assert first, "first run must mutate the edge"
    run(site, edge)
    assert edge.mutating_calls()[len(first):] == []


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_attack_playbook_engaged_is_p1():
    """attack-playbook-engaged is P1 with fingerprint attack-playbook-engaged:{zone.pk}.

    What would make this fail: filing as P2/P3, or keying the fingerprint on
    site pk so two sites on one zone hide each other's engagement.
    """
    from monitor.alert_rules import classify
    from monitor.attack_playbook import fingerprint_for, run
    from providers.fakes import FakeEdgeProtection

    site = _world("l5-p1")
    _attack_shaped(site)
    row = run(site, FakeEdgeProtection())
    assert classify("attack-playbook-engaged") == "p1"
    assert row.severity == Finding.Severity.P1
    assert row.fingerprint == fingerprint_for(site.dns_zone)
    assert row.fingerprint == f"attack-playbook-engaged:{site.dns_zone.pk}"
    assert EDGE_TOKEN not in f"{row.title}{row.body}{row.fix_action}"
    assert DNS_TOKEN not in f"{row.title}{row.body}{row.fix_action}"


@pytest.mark.req("SEC-L5-NEVER-SCALE-ATTACK")
def test_refuse_if_attack_blocks_scale():
    """refuse_if_attack raises a named refuse while the playbook is engaged (C4).

    What would make this fail: returning None during an open engagement, so
    Phase 6 could scale attack-shaped load.
    """
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection
    from scaling.attack_gate import AttackRefuse, refuse_if_attack

    site = _world("l5-gate")
    _attack_shaped(site)
    row = run(site, FakeEdgeProtection())
    with pytest.raises(AttackRefuse) as exc:
        refuse_if_attack(site)
    assert exc.value.finding.pk == row.pk
    quiet = _world("l5-gate-quiet")
    assert refuse_if_attack(quiet) is None


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_pager_click_url_is_hash_findings():
    """Pager deep link is {HUB_PUBLIC_URL}/#/findings/{id} (hash-only SPA).

    What would make this fail: a path-router /findings/{id} the SPA never
    mounts, so the ntfy click opens a blank Hub.
    """
    from monitor.attack_playbook import run
    from monitor.pager import get_pager
    from providers.fakes import FakeEdgeProtection

    site = _world("l5-click")
    _attack_shaped(site)
    row = run(site, FakeEdgeProtection())
    click = get_pager().published[-1]["click_url"]
    base = settings.HUB_PUBLIC_URL.rstrip("/")
    assert click == f"{base}/#/findings/{row.pk}"
    assert f"{base}/findings/{row.pk}" != click


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_dns_client_never_loads_edge_token_ref(monkeypatch):
    """dns_provider_for loads dns_token_ref only (D-057 / SEC-B2).

    What would make this fail: the DNS client reading edge_token_ref so a
    Firewall-edit token rides the DNS adapter (or the reverse leak).
    """
    from providers.cloudflare import CloudflareDnsProvider
    from providers.registry import dns_provider_for

    dns_src = _class_or_func_source(
        REPO / "providers" / "cloudflare.py", class_name="CloudflareDnsProvider",
    )
    ctor_src = _class_or_func_source(
        REPO / "providers" / "registry.py", func_name="dns_provider_for",
    )
    assert not _attr_loads(dns_src, "edge_token_ref")
    assert not _attr_loads(ctor_src, "edge_token_ref")

    site = _world("l5-dns-wall", dns_token=DNS_TOKEN, edge_token=EDGE_TOKEN)
    zone = site.dns_zone
    http = _http(monkeypatch, _scope_routes(zone))
    provider = dns_provider_for(zone)
    assert isinstance(provider, CloudflareDnsProvider)
    blob = repr(http.requests)
    assert DNS_TOKEN in blob
    assert EDGE_TOKEN not in blob
    for _method, _path, headers, _body in http.requests:
        assert headers.get("Authorization") == f"Bearer {DNS_TOKEN}"


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_edge_client_never_loads_dns_token_ref(monkeypatch):
    """edge_protection_for loads edge_token_ref only (D-057 / SEC-B2).

    What would make this fail: CloudflareEdge authorizing with the DNS
    token, which must never grow Firewall:Edit.
    """
    from providers.cloudflare import CloudflareEdge
    from providers.registry import edge_protection_for

    edge_src = _class_or_func_source(
        REPO / "providers" / "cloudflare.py", class_name="CloudflareEdge",
    )
    ctor_src = _class_or_func_source(
        REPO / "providers" / "registry.py", func_name="edge_protection_for",
    )
    assert not _attr_loads(edge_src, "dns_token_ref")
    assert not _attr_loads(ctor_src, "dns_token_ref")

    site = _world("l5-edge-wall", dns_token=DNS_TOKEN, edge_token=EDGE_TOKEN)
    zone = site.dns_zone
    http = _http(monkeypatch, _scope_routes(zone))
    edge = edge_protection_for(zone)
    assert isinstance(edge, CloudflareEdge)
    blob = repr(http.requests)
    assert EDGE_TOKEN in blob
    assert DNS_TOKEN not in blob
    for _method, _path, headers, _body in http.requests:
        assert headers.get("Authorization") == f"Bearer {EDGE_TOKEN}"
    assert EDGE_TOKEN not in repr(edge)
    assert DNS_TOKEN not in repr(edge)
