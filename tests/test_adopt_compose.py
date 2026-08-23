"""Compose-aware adoption plan (Phase 3b Task 4 / design note §1.1 a,b,e).

Reader only: classify the Project-tree compose into one V5 Site, file
Findings, register volumes, write edge_owner. Never flip, never paste,
never walk /srv/sites/{slug}, never put DATABASE_URL on a Finding.
"""
import inspect
import json
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.django_db, pytest.mark.req("PROV-J7-COMPOSE-AWARE-ADOPT")]

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "compose"
DB_URL = "postgres://adopt:super-secret-db-url@db:5432/app"


def _project_from_fixture(name, slug):
    from core.models import Project, Site

    project = Project.objects.create(
        name=slug,
        slug=slug,
        source_kind=Project.Source.LOCAL_PATH,
        local_path=str(FIXTURES / name),
    )
    site = Site.objects.create(
        project=project,
        name=slug,
        exposure=Site.Exposure.MESH_ONLY,
    )
    return project, site


def _project_from_text(tmp_path, slug, compose_text, filename="docker-compose.yml"):
    from core.models import Project, Site

    root = tmp_path / slug
    root.mkdir()
    (root / filename).write_text(compose_text)
    project = Project.objects.create(
        name=slug,
        slug=slug,
        source_kind=Project.Source.LOCAL_PATH,
        local_path=str(root),
    )
    site = Site.objects.create(
        project=project,
        name=slug,
        exposure=Site.Exposure.MESH_ONLY,
    )
    return project, site


def _finding_copy(row):
    return f"{row.title}\n{row.body}\n{row.fix_action}"


def _assert_no_secret_on_findings():
    from core.models import Finding

    assert not Finding.objects.filter(fingerprint__startswith="site-dns-unbound").exists()
    for row in Finding.objects.all():
        blob = _finding_copy(row)
        assert DB_URL not in blob
        assert "DATABASE_URL" not in blob
        assert row.title.strip()
        assert row.body.strip()
        assert row.fix_action.strip()


def test_worker_beat_and_oneshot_migrate_are_classified():
    """Sidecars compress into V5 jobs, not extra Sites.

    What would make this fail: treating worker/beat/migrate as a second
    public service, or leaving them unclassified so the plan looks like
    web-only.
    """
    from provision.adopt import classify_services, read_compose

    doc = read_compose(FIXTURES / "web-worker-beat-migrate")
    roles = classify_services(doc)
    assert roles["web"] == "web"
    assert roles["worker"] == "worker"
    assert roles["beat-scheduler"] == "beat"
    assert roles["one-shot migrate"] == "migrate"
    assert roles["db"] == "db"
    assert roles["cache"] == "redis"
    assert roles["site-owned edge"] is None


def test_site_owned_edge_container_is_recorded_as_a_decision_on_the_site():
    """Unambiguous caddy-on-80/443 writes Site.edge_owner once.

    What would make this fail: leaving the default host_caddy, inventing a
    second Site for Caddy, or prompting per run instead of recording the
    decision on the Site.
    """
    from core.models import Site
    from provision.adopt import adoption_plan

    project, site = _project_from_fixture("web-site-caddy", "p3b-edge-caddy")
    assert site.edge_owner == Site.EdgeOwner.HOST_CADDY
    plan = adoption_plan(project)
    site.refresh_from_db()
    assert site.edge_owner == Site.EdgeOwner.SITE_CADDY
    assert plan.classified["site-owned edge"] == "caddy"
    assert plan.refused is False
    assert plan.blocked is False
    _assert_no_secret_on_findings()


def test_named_volumes_appear_in_the_plan():
    """Every compose named volume is registered on SiteVolume (N6).

    What would make this fail: dropping pgdata/media, walking bind mounts
    as named volumes, or returning names without writing SiteVolume rows.
    """
    from core.models import SiteVolume
    from provision.adopt import adoption_plan

    project, site = _project_from_fixture("web-worker-beat-migrate", "p3b-vols")
    plan = adoption_plan(project)
    names = {volume.name for volume in plan.volumes}
    assert names == {"pgdata", "media"}
    assert SiteVolume.objects.filter(site=site, name="pgdata").exists()
    assert SiteVolume.objects.filter(site=site, name="media").exists()
    pg = SiteVolume.objects.get(site=site, name="pgdata")
    assert pg.container_path == "/var/lib/postgresql/data"
    media = SiteVolume.objects.get(site=site, name="media")
    assert media.container_path == "/app/media"
    _assert_no_secret_on_findings()


def test_parser_executes_nothing(tmp_path):
    """read_compose is yaml.safe_load on bytes. Nothing runs.

    What would make this fail: yaml.load (unsafe), subprocessing compose,
    or honouring a !!python constructor / a service command.
    """
    from provision.adopt import read_compose

    marker = tmp_path / "executed"
    (tmp_path / "docker-compose.yml").write_text(
        "!!python/object/apply:os.system\n"
        f"- touch {marker}\n"
    )
    with pytest.raises(yaml.YAMLError):
        read_compose(tmp_path)
    assert not marker.exists()

    (tmp_path / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: blog:prod\n"
        f"    command: ['touch', '{marker}']\n"
    )
    doc = read_compose(tmp_path)
    assert doc["services"]["web"]["command"] == ["touch", str(marker)]
    assert not marker.exists()

    assert list(inspect.signature(read_compose).parameters) == ["path"]


def test_single_container_stack_still_produces_one_manifest():
    """Web-only still compresses to one V5 service proposal, not a Manifest row.

    What would make this fail: refusing a single container, emitting two
    service components, or materializing a deploys.Manifest (that is execute).
    """
    from deploys.models import Manifest
    from provision.adopt import adoption_plan

    project, site = _project_from_fixture("web-only", "p3b-web-only")
    plan = adoption_plan(project)
    assert plan.refused is False
    assert plan.manifest is not None
    assert plan.manifest["components"]["service"]["name"] == "web"
    assert plan.manifest["components"]["jobs"] == []
    assert Manifest.objects.filter(site=site).count() == 0
    site.refresh_from_db()
    from core.models import Site

    assert site.edge_owner == Site.EdgeOwner.HOST_CADDY


def test_plan_findings_carry_what_why_and_fix():
    """Every Finding is §6.6 copy. The db URL never appears.

    What would make this fail: empty title/body/fix_action, filing through
    Finding.objects.create, or echoing DATABASE_URL into the inbox.
    """
    from core.findings import finding as finding_helper
    from core.models import Finding
    from provision.adopt import adoption_plan

    project, site = _project_from_fixture("web-worker-beat-migrate", "p3b-copy")
    plan = adoption_plan(project)
    assert plan.findings
    assert all(row.pk for row in plan.findings)
    for row in plan.findings:
        assert row.source_engine == "adopt"
        blob = _finding_copy(row)
        assert DB_URL not in blob
        assert "DATABASE_URL" not in blob
    _assert_no_secret_on_findings()
    wire = json.dumps(
        [{"title": r.title, "body": r.body, "fix_action": r.fix_action}
         for r in Finding.objects.all()]
    )
    assert DB_URL not in wire
    assert "DATABASE_URL" not in wire
    assert finding_helper.__module__ == "core.findings"


def test_two_public_services_refuse_with_a_finding():
    """Two uncompressible public services → Finding, no V5 proposal.

    What would make this fail: inventing a multi-container Site, picking
    one service silently, or refusing without a what/why/fix Finding.
    """
    from core.models import Finding
    from deploys.models import Manifest
    from provision.adopt import adoption_plan

    project, site = _project_from_fixture("two-public", "p3b-two-pub")
    plan = adoption_plan(project)
    assert plan.refused is True
    assert plan.manifest is None
    assert Manifest.objects.filter(site=site).count() == 0
    rows = list(Finding.objects.filter(source_engine="adopt"))
    assert rows
    assert any("blog" in _finding_copy(row) and "shop" in _finding_copy(row) for row in rows)
    _assert_no_secret_on_findings()


def test_compose_is_read_from_project_tree_not_a_paste(tmp_path):
    """Compose comes from local_path / clone. No paste. No /srv/sites walk.

    What would make this fail: a paste= argument, preferring
    docker-compose.yml over docker-compose.prod.yml, or opening
    /srv/sites/{slug} as a compose root.
    """
    from provision.adopt import adoption_plan, read_compose

    root = tmp_path / "tree"
    root.mkdir()
    (root / "docker-compose.yml").write_text(
        "services:\n"
        "  decoy:\n"
        "    image: decoy:1\n"
        "    ports: ['9000:9000']\n"
    )
    (root / "docker-compose.prod.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: app:1\n"
        "    ports: ['8000:8000']\n"
    )
    (root / "compose.yaml").write_text(
        "services:\n"
        "  other:\n"
        "    image: other:1\n"
        "    ports: ['9001:9001']\n"
    )
    from core.models import Project, Site

    project = Project.objects.create(
        name="p3b-tree",
        slug="p3b-tree",
        source_kind=Project.Source.LOCAL_PATH,
        local_path=str(root),
    )
    Site.objects.create(
        project=project,
        name="p3b-tree",
        exposure=Site.Exposure.MESH_ONLY,
    )
    with pytest.raises(TypeError):
        adoption_plan(project, paste="services:\n  pasted:\n    image: x\n")
    with pytest.raises(TypeError):
        read_compose(root, paste="services: {}\n")

    plan = adoption_plan(project)
    assert plan.classified["web"] == "web"
    assert plan.refused is False

    src = Path(inspect.getfile(adoption_plan)).read_text(encoding="utf-8")
    assert "/srv/sites" not in src
    assert "paste" not in inspect.signature(adoption_plan).parameters
    assert list(inspect.signature(adoption_plan).parameters) == ["project"]


@pytest.fixture
def auth_client(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


def test_ambiguous_edge_blocks_until_edge_owner_is_set(tmp_path, auth_client):
    """Non-edge image on 80/443 files a Finding; PATCH unblocks.

    What would make this fail: writing site_caddy anyway, leaving the
    Finding open after PATCH, or re-filing and re-blocking a decided Site.
    """
    from core.models import Finding, Site
    from provision.adopt import adoption_plan

    compose = (
        "services:\n"
        "  web:\n"
        "    image: myapp:1\n"
        "    ports: ['80:80', '443:443']\n"
    )
    project, site = _project_from_text(tmp_path, "p3b-amb-block", compose)
    plan = adoption_plan(project)
    assert plan.blocked is True
    assert plan.refused is False
    site.refresh_from_db()
    assert site.edge_owner == Site.EdgeOwner.HOST_CADDY
    row = Finding.objects.get(fingerprint=f"adopt-edge-ambiguous:{site.pk}")
    assert row.state == Finding.State.OPEN
    assert row.title.strip() and row.body.strip() and row.fix_action.strip()

    patched = auth_client.patch(
        f"/api/v1/sites/{site.pk}/",
        data={"edge_owner": "site_caddy"},
        content_type="application/json",
    )
    assert patched.status_code == 200

    plan2 = adoption_plan(project)
    assert plan2.blocked is False
    site.refresh_from_db()
    assert site.edge_owner == Site.EdgeOwner.SITE_CADDY
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    _assert_no_secret_on_findings()


def test_ambiguous_edge_is_non_edge_image_on_80_443_or_two_edge_images(tmp_path):
    """Ambiguous is exactly I-edge: mystery 80/443 publisher, or two edge images.

    What would make this fail: treating myapp:80 as site_caddy, or picking
    caddy when nginx also publishes 443.
    """
    from core.models import Finding, Site
    from provision.adopt import adoption_plan

    mystery, mystery_site = _project_from_text(
        tmp_path,
        "p3b-amb-mystery",
        "services:\n"
        "  edge:\n"
        "    image: myapp:1\n"
        "    ports: ['80:80']\n",
    )
    plan = adoption_plan(mystery)
    assert plan.blocked is True
    mystery_site.refresh_from_db()
    assert mystery_site.edge_owner == Site.EdgeOwner.HOST_CADDY
    assert Finding.objects.filter(
        fingerprint=f"adopt-edge-ambiguous:{mystery_site.pk}",
        state=Finding.State.OPEN,
    ).exists()

    two, two_site = _project_from_text(
        tmp_path,
        "p3b-amb-two",
        "services:\n"
        "  web:\n"
        "    image: app:1\n"
        "  caddy:\n"
        "    image: caddy:2\n"
        "    ports: ['80:80']\n"
        "  nginx:\n"
        "    image: nginx:1.27\n"
        "    ports: ['443:443']\n",
    )
    plan2 = adoption_plan(two)
    assert plan2.blocked is True
    two_site.refresh_from_db()
    assert two_site.edge_owner == Site.EdgeOwner.HOST_CADDY
    assert Finding.objects.filter(
        fingerprint=f"adopt-edge-ambiguous:{two_site.pk}",
        state=Finding.State.OPEN,
    ).exists()
    _assert_no_secret_on_findings()
