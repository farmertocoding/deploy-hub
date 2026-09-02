"""Provisioner task. Queue is the default `deploys` — this is not a probe."""
from celery import shared_task


@shared_task(ignore_result=True)
def run_backup_nightly():
    """Beat `backup-nightly`. Persist each unit; missing dumps file P1."""
    from provision.backup import run_nightly

    return run_nightly()


def envelope_for_provision(target_id):
    from core.models import Target, require_workspace
    from core.task_envelope import wrap

    target = Target.objects.select_related("zone").get(pk=target_id)
    return wrap(
        task="provision.tasks.provision_host",
        workspace_id=require_workspace(target).pk,
        resource_type="Target",
        resource_id=target_id,
    )


@shared_task
def provision_host(target_id, envelope=None, *, live_beat_jobs=None, profile="target"):
    from core.models import Target
    from core.ssh import SshTransport
    from core.task_envelope import EnvelopeError, reauthorize
    from provision.service import provision_host as run

    if envelope is None:
        return {"ok": False, "reason": "envelope"}
    target = Target.objects.select_related("zone").get(pk=target_id)
    try:
        reauthorize(
            envelope,
            resource=target,
            task="provision.tasks.provision_host",
            resource_id=str(target_id),
        )
    except EnvelopeError:
        return {"ok": False, "reason": "envelope"}
    result = run(
        target,
        SshTransport(target),
        live_beat_jobs=live_beat_jobs or (),
        profile=profile,
    )
    return {"allowed": result.allowed, "explanation": result.explanation}


@shared_task
def rotate_ssh_keys(*, force=False, transport_for=None, now=None):
    """Beat ssh-rotate-quarterly: dual-key rotate every READY SSH target."""
    from provision.ssh_rotate import rotate_all

    run = rotate_all(transport_for=transport_for, force=force, now=now)
    return {"ok": True, "status": run.status, "kind": run.kind}
