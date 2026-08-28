"""Flag 24h ephemeral overflow leftovers. Does not terminate (D-113)."""
from django.utils import timezone

from core.models import AuditEvent, Site, SiteInstance, Target, default_workspace
from monitor.alerts import raise_alert

STALE_S = 86400
TITLE = "Forgotten ephemeral overflow (past 24 hours)"
FIX_ACTION = "Scale in overflow to stop billing."


def reap_stale_ephemerals(*, now=None):
    """File ephemeral-overflow-orphan Findings. Never terminate."""
    now = now or timezone.now()
    flagged = []
    primary_ids = set(
        Site.objects.exclude(primary_target_id=None)
        .values_list("primary_target_id", flat=True)
    )
    rows = Target.objects.filter(
        kind=Target.Kind.AWS_EC2,
        lifecycle=Target.Lifecycle.EPHEMERAL,
        status__in=[
            Target.Status.READY,
            Target.Status.ERROR,
            Target.Status.PENDING,
        ],
    )
    for target in rows:
        if target.pk in primary_ids:
            continue
        birth = (
            AuditEvent.objects.filter(
                action="instance.create",
                object_type="Target",
                object_id=str(target.pk),
            )
            .order_by("ts")
            .first()
        )
        if birth is None:
            if not (target.provider_ref or "").strip():
                continue
            stale = True
        else:
            stale = (now - birth.ts).total_seconds() >= STALE_S
        if not stale:
            continue
        inst = SiteInstance.objects.filter(target=target).select_related("site").first()
        domain = ""
        if inst is not None:
            domain = inst.site.domain or inst.site.name
        body = (
            f"{target.host} has been ephemeral more than 24 hours. "
            f"propose-mode does not launch. Ack does not stop billing."
        )
        if domain:
            body += f" Scale in overflow on site {domain}."
        row = raise_alert(
            "ephemeral-overflow-orphan",
            f"target:{target.host}",
            workspace=default_workspace(),
            fingerprint=f"ephemeral-overflow-orphan:{target.pk}",
            title=TITLE,
            body=body,
            fix_action=FIX_ACTION,
        )
        flagged.append(row)
    return flagged
