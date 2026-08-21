"""Kill-matrix: crash after step n, then resume to succeeded (REL-P3)."""
import pytest
from pipeline_fakes import PipelineTransport, queued_deployment

from deploys.models import Deployment, DeploymentStep
from providers.fakes import FakeDnsProvider

pytestmark = pytest.mark.django_db

STEP_NAMES = list(DeploymentStep.Name.values)


def _side_effect_happened(seq, transport, dns, slug, deployment_id):
    """The crashed step's ensure_* ran before the hook (not the skeleton no-op)."""
    if seq == 1:
        return any(
            kind == "run" and isinstance(argv, list) and argv[:1] == ["docker"]
            and "build" in argv
            for kind, argv in transport.calls
        )
    if seq == 2:
        return any(
            kind == "probe" and argv[:3] == ["docker", "image", "inspect"]
            for kind, argv in transport.calls
        )
    if seq == 3:
        return f"site-{slug}-data" in transport.volumes
    if seq == 4:
        return f"site-{slug}-{deployment_id}" in transport.containers
    if seq == 5:
        return any(
            kind == "probe" and argv and argv[0] == "curl" and "2019" not in " ".join(argv)
            for kind, argv in transport.calls
        )
    if seq == 6:
        return bool(dns.list_records("example.test"))
    if seq == 7:
        return f"site-{slug}" in transport.routes
    if seq == 8:
        return any(
            kind == "probe" and argv and argv[0] == "curl" and "443" in " ".join(argv)
            for kind, argv in transport.calls
        )
    if seq == 9:
        step = Deployment.objects.get(pk=deployment_id).steps.get(seq=9)
        return bool((step.artifacts or {}).get("grace_deadline"))
    return False


@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
@pytest.mark.parametrize("seq", range(1, 10))
def test_crash_after_step_n_resumes(seq, monkeypatch):
    """HUB_TEST_CRASH_AFTER_STEP=n raises after ensure_*; a second execute resumes.

    What would make this fail: crashing before the step's ensure_*, marking
    that step succeeded, or the resume leaving the deployment short of succeeded.
    """
    from deploys.pipeline import CRASH_AFTER_ENV, execute

    slug = f"crash-{seq}"
    _site, deployment = queued_deployment(slug)
    transport = PipelineTransport()
    dns = FakeDnsProvider()

    monkeypatch.setenv(CRASH_AFTER_ENV, str(seq))
    with pytest.raises(RuntimeError, match=CRASH_AFTER_ENV):
        execute(deployment.pk, transport=transport, dns=dns)

    deployment.refresh_from_db()
    assert deployment.status != Deployment.Status.SUCCEEDED
    crashed = deployment.steps.get(seq=seq)
    assert crashed.status != DeploymentStep.Status.SUCCEEDED
    assert crashed.name == STEP_NAMES[seq - 1]
    for prior in deployment.steps.filter(seq__lt=seq):
        assert prior.status == DeploymentStep.Status.SUCCEEDED, prior.name
    for later in deployment.steps.filter(seq__gt=seq):
        assert later.status == DeploymentStep.Status.PENDING, later.name
    assert _side_effect_happened(seq, transport, dns, slug, deployment.pk), (
        f"step {seq} ensure_* did not run before the crash hook"
    )

    monkeypatch.delenv(CRASH_AFTER_ENV)
    execute(deployment.pk, transport=transport, dns=dns)
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED
    assert list(
        deployment.steps.order_by("seq").values_list("status", flat=True),
    ) == [DeploymentStep.Status.SUCCEEDED] * 9
