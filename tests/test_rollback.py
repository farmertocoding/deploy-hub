"""Rollback executes a new Deployment that re-applies artifacts; volumes survive."""
import pytest
from pipeline_fakes import PipelineTransport, queued_deployment

from deploys.models import Deployment, DeploymentArtifact, DeploymentStep
from providers.fakes import FakeDnsProvider

pytestmark = pytest.mark.django_db


def _volume_rm_argvs(transport):
    found = []
    for kind, payload in transport.mutating_calls():
        if kind != "run" or not isinstance(payload, list):
            continue
        argv = list(payload)
        try:
            i = argv.index("volume")
        except ValueError:
            continue
        if i + 1 < len(argv) and argv[i + 1] == "rm":
            found.append(argv)
    return found


def _deploy(slug):
    from deploys.pipeline import execute

    site, deployment = queued_deployment(slug)
    transport = PipelineTransport()
    dns = FakeDnsProvider()
    result = execute(deployment.pk, transport=transport, dns=dns)
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED, result
    return site, deployment, transport, dns


@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_rollback_is_new_deployment_row():
    """rollback() inserts a second Deployment with rollback_of set and executes it.

    What would make this fail: mutating the original row to rolled_back, or
    returning a row that was never executed through rollback().
    """
    from deploys.pipeline import rollback

    _site, original, transport, dns = _deploy("rb-row")
    original_status = original.status

    result = rollback(original.pk, transport=transport, dns=dns)
    original.refresh_from_db()
    created = Deployment.objects.get(rollback_of=original)

    assert created.pk != original.pk
    assert created.rollback_of_id == original.pk
    assert created.manifest_id == original.manifest_id
    assert original.status == original_status == Deployment.Status.SUCCEEDED
    assert original.rollbacks.get().pk == created.pk
    assert created.status == Deployment.Status.SUCCEEDED
    assert result["status"] == Deployment.Status.SUCCEEDED


@pytest.mark.req("REL-P4-ARTIFACT-SNAPSHOTS")
def test_rollback_reapplies_artifact_set():
    """The rollback Deployment's artifact kinds and contents match the original.

    What would make this fail: inventing a new dockerfile/caddy/dns/env/firewall
    set, or snapshotting only a subset of the original kinds.
    """
    from deploys.pipeline import rollback

    _site, original, transport, dns = _deploy("rb-art")
    original_rows = list(
        DeploymentArtifact.objects.filter(deployment=original).order_by("kind"),
    )
    assert original_rows, "first deploy must snapshot artifacts before rollback"

    rollback(original.pk, transport=transport, dns=dns)
    created = Deployment.objects.get(rollback_of=original)
    new_rows = list(
        DeploymentArtifact.objects.filter(deployment=created).order_by("kind"),
    )
    assert [(r.kind, r.content) for r in new_rows] == [
        (r.kind, r.content) for r in original_rows
    ]


@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
def test_rollback_does_not_remove_named_volume():
    """Rollback must not docker volume rm; site-{slug}-data stays.

    What would make this fail: a volume rm argv on the rollback path, or
    dropping the named volume from the transport's present set.
    """
    from deploys.pipeline import rollback

    site, original, transport, dns = _deploy("rb-vol")
    volume = f"site-{site.name}-data"
    assert volume in transport.volumes
    transport.calls.clear()

    rollback(original.pk, transport=transport, dns=dns)

    assert _volume_rm_argvs(transport) == []
    assert volume in transport.volumes
    assert not any(
        isinstance(payload, list) and "volume" in payload and "rm" in payload
        for kind, payload in transport.mutating_calls()
        if kind == "run"
    )
    original.refresh_from_db()
    assert original.status == Deployment.Status.SUCCEEDED
    assert original.steps.filter(status=DeploymentStep.Status.SUCCEEDED).count() == 9
