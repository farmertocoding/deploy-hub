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


@pytest.mark.req("REL-P4-ARTIFACT-SNAPSHOTS")
def test_rollback_overlay_dockerfile_is_what_gets_built():
    """Rollback packs snapshot dockerfile bytes, not a body re-generation.

    What would make this fail: _assemble_desired copying the overlay while
    ensure_build still tars _dockerfile_from_body(body).
    """
    import io
    import tarfile

    from deploys.pipeline import rollback
    from deploys.steps import _dockerfile_from_body

    _site, original, transport, dns = _deploy("rb-df")
    generated = _dockerfile_from_body(original.manifest.body or {})
    overlay = "FROM alpine:3.20\n# rollback-snapshot-bytes\n"
    assert overlay != generated

    row = DeploymentArtifact.objects.get(deployment=original, kind="dockerfile")
    row.content = overlay
    row.save(update_fields=["content"])

    transport.images.clear()
    transport.calls.clear()
    rollback(original.pk, transport=transport, dns=dns)

    packed = None
    for kind, remote in transport.calls:
        if kind != "put":
            continue
        payload = transport.files.get(remote)
        if not isinstance(payload, (bytes, bytearray)):
            continue
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as tf:
                member = tf.extractfile("Dockerfile") or tf.extractfile("./Dockerfile")
                if member is not None:
                    packed = member.read().decode()
                    break
        except tarfile.TarError:
            continue
    assert packed == overlay
    assert "npm ci" not in packed


@pytest.mark.req("SEC-P5-BREAK-GLASS")
@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_cutover_writes_runbook_when_artifacts_exist_but_remote_missing():
    """Resume after a failed runbook put still writes the remote 0400 file.

    What would make this fail: text_artifacts.exists() returning before
    write_runbook when BREAK-GLASS.md is not on the target.
    """
    from deploys.pipeline import _assemble_desired, _snapshot_and_runbook

    site, deployment, transport, dns = _deploy("rb-rbk")
    assert deployment.text_artifacts.exists()
    runbook = f"/srv/sites/{site.name}/BREAK-GLASS.md"
    assert runbook in transport.files
    transport.files.pop(runbook)
    transport.calls.clear()

    desired = _assemble_desired(
        deployment, transport=transport, dns=dns, sleep=None,
    )
    _snapshot_and_runbook(deployment, desired)

    assert runbook in transport.files
    assert any(
        kind == "put" and remote == runbook
        for kind, remote in transport.mutating_calls()
    )
    assert deployment.text_artifacts.count() == 5


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_cutover_second_skip_when_snapshot_and_runbook_landed():
    """When artifacts and the remote runbook are both present, cutover is silent.

    What would make this fail: mkdir/chmod/put on a second cutover that already
    landed both, so T1 second-deploy mutating_calls is never empty.
    """
    from deploys.pipeline import _assemble_desired, _snapshot_and_runbook

    _site, deployment, transport, dns = _deploy("rb-both")
    transport.calls.clear()
    desired = _assemble_desired(
        deployment, transport=transport, dns=dns, sleep=None,
    )
    _snapshot_and_runbook(deployment, desired)
    assert transport.mutating_calls() == []
