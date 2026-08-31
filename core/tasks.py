"""Celery delivery for the durable HUD command outbox."""
from celery import shared_task


@shared_task(ignore_result=True)
def process_hud_outbox(outbox_id, envelope=None):
    from core.hud.operations import process_outbox
    from core.models import HudCommandOutbox
    from core.task_envelope import EnvelopeError, reauthorize

    if envelope is None:
        return {"ok": False, "reason": "envelope"}
    try:
        row = HudCommandOutbox.objects.select_related("operation").get(pk=outbox_id)
        reauthorize(
            envelope,
            resource=row,
            task="core.tasks.process_hud_outbox",
            resource_id=str(outbox_id),
        )
    except (HudCommandOutbox.DoesNotExist, EnvelopeError):
        return {"ok": False, "reason": "envelope"}
    return process_outbox(outbox_id)


@shared_task(ignore_result=True)
def ship_audit_trail():
    from core.audit_ship import ship

    return ship()


@shared_task(ignore_result=True)
def drain_hud_outbox(limit=100):
    from core.hud.operations import pending_outbox_ids

    ids = pending_outbox_ids(limit=limit)
    for outbox_id in ids:
        from core.hud.operations import envelope_for_outbox

        process_hud_outbox.delay(outbox_id, envelope_for_outbox(outbox_id))
    return {"ok": True, "queued": len(ids)}
