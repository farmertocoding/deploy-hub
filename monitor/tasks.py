"""Collector Beat entry. Lives on queue ``probes`` via ``monitor.*``."""
from celery import shared_task


@shared_task
def collect_all(*, transport_for=None, sleep=None, now=None):
    from core.models import Target
    from core.ssh import SshTransport
    from monitor.collector import collect

    factory = transport_for or SshTransport
    payloads = []
    for target in Target.objects.filter(status=Target.Status.READY):
        try:
            payloads.append(
                collect(target, factory(target), now=now, sleep=sleep)
            )
        except Exception:
            continue
    return payloads
