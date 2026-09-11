"""Reconciler Beat entry. Lives on queue ``control`` via ``reconcile.*``."""
from celery import shared_task

from core.audit import audit
from reconcile.loop import GLOBAL_MUTATION_BUDGET


def envelope_for_tick():
    from core.task_envelope import wrap

    return wrap(
        task="reconcile.tasks.tick_all",
        workspace_id=0,
        resource_type="fleet",
        resource_id="reconcile-tick",
    )


@shared_task
def dispatch_tick_all(**kwargs):
    """Beat entry: sign, then tick. Unsigned ``tick_all`` is refused."""
    return tick_all(envelope=envelope_for_tick(), **kwargs)


@shared_task
def tick_all(*, envelope=None, budget=None, transport_for=None):
    from core.models import SiteInstance
    from core.ssh import SshTransport
    from core.task_envelope import EnvelopeError, reauthorize
    from reconcile.loop import tick

    if envelope is None:
        return {"ok": False, "reason": "envelope"}
    try:
        reauthorize(
            envelope,
            task="reconcile.tasks.tick_all",
            resource_id="reconcile-tick",
        )
    except EnvelopeError:
        return {"ok": False, "reason": "envelope"}

    remaining = GLOBAL_MUTATION_BUDGET if budget is None else budget
    factory = transport_for or SshTransport
    for instance in SiteInstance.objects.select_related("site", "target"):
        if remaining <= 0:
            break
        try:
            result = tick(
                instance.site,
                transport=factory(instance.target),
                jitter=0,
                budget=remaining,
                instance=instance,
            )
        except Exception as exc:
            audit(
                "reconcile-tick-failed",
                instance,
                source="celery",
                error=type(exc).__name__,
            )
            continue
        remaining -= int((result or {}).get("mutations") or 0)
    return {"remaining": remaining}
