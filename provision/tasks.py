"""Provisioner task. Queue is the default `deploys` — this is not a probe."""
from celery import shared_task


@shared_task(ignore_result=True)
def run_backup_nightly():
    """Beat `backup-nightly`. Persist each unit; missing dumps file P1."""
    from provision.backup import run_nightly

    return run_nightly()


@shared_task
def provision_host(target_id, *, live_beat_jobs=None, profile="target"):
    from core.models import Target
    from core.ssh import SshTransport
    from provision.service import provision_host as run

    target = Target.objects.get(pk=target_id)
    result = run(
        target,
        SshTransport(target),
        live_beat_jobs=live_beat_jobs or (),
        profile=profile,
    )
    return {"allowed": result.allowed, "explanation": result.explanation}
