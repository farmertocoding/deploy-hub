"""DeploymentArtifact snapshots: every generated kind, never secret values (P4)."""
import pytest

SECRET = "VAULT-TEST-PLAINTEXT-MARKER-do-not-log"
KINDS = {
    "dockerfile",
    "caddy_route",
    "dns_set",
    "env_names",
    "firewall_argv",
    "image_tag",
}


def _deployment():
    from core.models import Project, Site
    from deploys.models import Deployment, Manifest

    project = Project.objects.create(name="art", slug="p-art")
    site = Site.objects.create(project=project, name="art")
    manifest = Manifest.objects.create(
        site=site,
        version=1,
        body={"env": {"DATABASE_URL": SECRET, "API_KEY": SECRET}},
    )
    return Deployment.objects.create(manifest=manifest)


def _desired(deployment, *, extra=None):
    desired = {
        "transport": None,
        "site_slug": "art",
        "deployment_id": deployment.pk,
        "manifest_body": deployment.manifest.body,
        "deployment": deployment,
        "dockerfile": "FROM python:3.12-slim\nWORKDIR /app\n",
        "caddy_route": '{"@id": "site-art"}',
        "dns_set": '[{"name": "art.example.com", "rtype": "A"}]',
        "env_names": ["DATABASE_URL", "API_KEY"],
        "firewall_argv": ["ufw", "allow", "80", "443"],
        "image_tag": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-deadbeefdeadbeef",
    }
    if extra:
        desired.update(extra)
    return desired


@pytest.mark.req("REL-P4-ARTIFACT-SNAPSHOTS")
@pytest.mark.django_db
def test_every_generated_artifact_snapshotted():
    """Each generated kind is stored as a DeploymentArtifact on the deployment.

    What would make this fail: dropping dockerfile, caddy route, dns set, env
    names, or firewall argv from the snapshot set.
    """
    from deploys.artifacts import snapshot_artifacts
    from deploys.models import DeploymentArtifact

    deployment = _deployment()
    snapshot_artifacts(_desired(deployment))
    kinds = set(
        DeploymentArtifact.objects.filter(deployment=deployment).values_list(
            "kind", flat=True,
        )
    )
    assert KINDS <= kinds, f"missing artifact kinds: {KINDS - kinds}"
    env = DeploymentArtifact.objects.get(deployment=deployment, kind="env_names")
    assert "DATABASE_URL" in env.content
    assert "API_KEY" in env.content
    docker = DeploymentArtifact.objects.get(deployment=deployment, kind="dockerfile")
    assert "FROM python:3.12-slim" in docker.content
    caddy = DeploymentArtifact.objects.get(deployment=deployment, kind="caddy_route")
    assert "site-art" in caddy.content
    dns = DeploymentArtifact.objects.get(deployment=deployment, kind="dns_set")
    assert "art.example.com" in dns.content
    fw = DeploymentArtifact.objects.get(deployment=deployment, kind="firewall_argv")
    assert "ufw" in fw.content
    tag = DeploymentArtifact.objects.get(deployment=deployment, kind="image_tag")
    assert "deadbeefdeadbeef" in tag.content


@pytest.mark.req("REL-P4-ARTIFACT-SNAPSHOTS")
@pytest.mark.django_db
def test_artifact_has_no_secret_values():
    """Planted env/body secret values must not appear in any artifact content.

    What would make this fail: snapshotting env values, dumping Manifest.body,
    or copying a planted secret into dockerfile/caddy/dns/firewall content.
    """
    from deploys.artifacts import snapshot_artifacts
    from deploys.models import DeploymentArtifact

    deployment = _deployment()
    snapshot_artifacts(_desired(deployment, extra={
        "env": {"DATABASE_URL": SECRET, "API_KEY": SECRET},
        "manifest_body": {
            "env": {"DATABASE_URL": SECRET},
            "secret": SECRET,
        },
    }))
    rows = list(DeploymentArtifact.objects.filter(deployment=deployment))
    assert rows
    for row in rows:
        assert SECRET not in row.content, f"{row.kind} leaked secret values"
