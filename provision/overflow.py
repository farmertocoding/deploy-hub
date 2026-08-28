"""T1 overflow enroll: propose-gated, still never auto (D-104 / D-105).

refuse_if_attack first, then ACCEPTED scale-out-proposal:{pk}, then
pick_overflow_home (hit refuses rent), then enroll_aws_target at t3.medium.
Gate EnrollError does not raise_alert, _retract, write Finding, or write CheckRun.
"""

from django.utils import timezone

from provision.aws_enroll import EnrollError, enroll_aws_target
from scaling.attack_gate import AttackRefuse, PartnerOverflowRefuse, refuse_if_attack
from scaling.constants import FIX_ACTION, OVERFLOW_SIZE
from scaling.destination import pick_overflow_home


def enroll_overflow_target(
    *,
    site,
    host,
    zone,
    confirm_name,
    provider=None,
    make_transport=None,
    now=None,
):
    """Enroll an ephemeral overflow Target only when the propose-gate is ACCEPTED."""
    try:
        refuse_if_attack(site)
    except (AttackRefuse, PartnerOverflowRefuse) as exc:
        raise EnrollError(str(exc)) from exc

    if confirm_name != host:
        raise EnrollError("Type the target host name to confirm.")

    from core.models import Finding

    row = Finding.objects.filter(
        workspace=site.project.workspace,
        fingerprint=f"scale-out-proposal:{site.pk}",
    ).first()
    if row is None or row.state != Finding.State.ACCEPTED:
        raise EnrollError(FIX_ACTION)

    picked, _cost, _size = pick_overflow_home(site, now=now or timezone.now())
    if picked is not None:
        raise EnrollError("idle registered machine exists; do not rent")

    return enroll_aws_target(
        host=host,
        name=host,
        zone=zone,
        instance_type=OVERFLOW_SIZE,
        provider=provider,
        make_transport=make_transport,
        spec={"tags": {"overflow_site": site.pk}},
    )
