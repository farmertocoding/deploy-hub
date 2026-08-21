"""Reconciler Beat entry. Lives on queue ``probes`` via ``reconcile.*``."""
from celery import shared_task


@shared_task
def tick_all():
    from core.models import Site
    from core.ssh import SshTransport
    from reconcile.loop import tick

    for site in Site.objects.exclude(primary_target=None):
        tick(site, transport=SshTransport(site.primary_target), jitter=0)
