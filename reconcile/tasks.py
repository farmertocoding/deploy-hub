"""Reconciler Beat entry. Lives on queue ``probes`` via ``reconcile.*``."""
from celery import shared_task

from reconcile.loop import GLOBAL_MUTATION_BUDGET


@shared_task
def tick_all(*, budget=None, transport_for=None):
    from core.models import SiteInstance
    from core.ssh import SshTransport
    from reconcile.loop import tick

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
        except Exception:
            continue
        remaining -= int((result or {}).get("mutations") or 0)
    return {"remaining": remaining}
