"""Collector and missed-drill Beat entries. Live on queue ``probes`` via ``monitor.*``."""
import time

from celery import shared_task

from core.audit import audit


@shared_task(ignore_result=True)
def collect_all(*, transport_for=None, sleep=None, now=None, monotonic=None):
    from core import locks
    from core.models import Target
    from core.ssh import SshTransport
    from monitor.collector import collect
    from monitor.traffic import ingest as ingest_traffic

    factory = transport_for or SshTransport
    mono = monotonic or time.monotonic
    started = mono()
    n = 0
    for target in Target.objects.filter(status=Target.Status.READY):
        lock = locks.acquire("target", target.pk, "collect", "collect-all")
        if lock is None:
            continue
        try:
            payload = collect(
                target, factory(target), now=now, sleep=sleep,
                tick_started=started, monotonic=mono,
            )
            ingest_traffic(target, payload)
            n += 1
        except Exception as exc:
            audit(
                "collector-failed",
                target,
                source="celery",
                error=type(exc).__name__,
            )
            continue
        finally:
            locks.release("target", target.pk, "collect", holder="collect-all")
    return {"ok": True, "n": n}


@shared_task(ignore_result=True)
def detect_missed_drills(*, now=None):
    from django.utils import timezone

    from monitor.drills import find_missed

    clock = now or timezone.now()
    missed = find_missed(clock)
    for kind in missed:
        audit("drill-missed", source="celery", severity="warning", kind=kind)
    return {"ok": True, "n": len(missed)}


@shared_task(ignore_result=True)
def run_hub_down_drill(*, duration_s=1800):
    from monitor.drills import run_hub_down_drill as body

    run = body(duration_s=duration_s)
    return {"ok": True, "status": run.status, "kind": run.kind}


@shared_task(ignore_result=True)
def run_reaper_drill(*, planted_name="hub-t3-orphan-weekly"):
    from monitor.drills import run_reaper_drill as body

    run = body(planted_name=planted_name)
    return {"ok": True, "status": run.status, "kind": run.kind}


@shared_task(ignore_result=True)
def run_restore_clean_drill():
    from monitor.drills import run_restore_clean_drill as body

    run = body()
    return {"ok": True, "status": run.status, "kind": run.kind}


@shared_task(ignore_result=True)
def audit_cf_token_scope():
    """Daily SEC-B5 token-scope audit (Task 2). Takes no args by design:
    nothing credential-shaped can ever appear in task args or the result."""
    from monitor.token_audit import audit_cloudflare_credentials

    run = audit_cloudflare_credentials()
    return {"ok": True, "status": run.status, "kind": run.kind}


@shared_task(ignore_result=True)
def probe_uptime():
    """Beat `probe-uptime` (60 s, queue probes): one HTTP probe cycle, then
    the dead-man ping — fired only when the cycle completed every target
    (§C7). No secret ever appears in args or the returned dict."""
    from monitor.deadman import ping_after_cycle
    from monitor.uptime import probe_cycle

    cycle = probe_cycle()
    outcome = ping_after_cycle(cycle)
    return {
        "ok": True,
        "completed": cycle["completed"],
        "n": cycle["n"],
        "pinged": outcome["pinged"],
    }
