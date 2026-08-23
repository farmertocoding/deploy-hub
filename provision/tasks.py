"""Provisioner task. Queue is the default `deploys` — this is not a probe."""
from celery import shared_task


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


@shared_task
def rotate_ssh_keys(*, force=False, transport_for=None, now=None):
    """Beat ssh-rotate-quarterly: dual-key rotate every READY SSH target."""
    from provision.ssh_rotate import rotate_all

    run = rotate_all(transport_for=transport_for, force=force, now=now)
    return {"ok": True, "status": run.status, "kind": run.kind}
