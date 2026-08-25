"""T1 overflow same-image deploy: pin live tag, skip BUILD+DNS, SHIP on overflow.

refuse_if_attack first, then ACCEPTED scale-out-proposal:{pk}, then ephemeral
READY non-primary, then idle-pick miss, then a succeeded image_tag pin.
Gate OverflowDeployError does not raise_alert, _retract, write Finding, or
write CheckRun. Execute in-process with the overflow transport; do not
queue the worker and do not default the site primary transport.
"""
from django.utils import timezone

from core.overflow_deploys import OverflowDeployError
from scaling.attack_gate import AttackRefuse, PartnerOverflowRefuse, refuse_if_attack
from scaling.constants import FIX_ACTION
from scaling.destination import pick_overflow_home


def overflow_copy_thunk(*args, **kwargs):
    """Port thunk: look up deploy_overflow_copy at call time (HTTP inject)."""
    from deploys import overflow as overflow_mod

    return overflow_mod.deploy_overflow_copy(*args, **kwargs)


def deploy_overflow_copy(
    site, target, *, transport=None, dns=None, sleep=None, cert_issuer=None,
):
    """Deploy the site's last succeeded image_tag onto an overflow Target."""
    try:
        refuse_if_attack(site)
    except (AttackRefuse, PartnerOverflowRefuse) as exc:
        raise OverflowDeployError(str(exc)) from exc

    from core.models import Finding, SiteInstance, Target
    from deploys import pipeline
    from deploys.models import Deployment, DeploymentStep

    row = Finding.objects.filter(
        fingerprint=f"scale-out-proposal:{site.pk}",
    ).first()
    if row is None or row.state != Finding.State.ACCEPTED:
        raise OverflowDeployError(FIX_ACTION)

    if (
        target.kind != Target.Kind.AWS_EC2
        or target.lifecycle != Target.Lifecycle.EPHEMERAL
        or target.status != Target.Status.READY
        or target.pk == site.primary_target_id
    ):
        raise OverflowDeployError(
            "overflow target must be a ready ephemeral aws_ec2 that is not "
            "the site primary"
        )

    picked, _cost, _size = pick_overflow_home(site, now=timezone.now())
    if picked is not None:
        raise OverflowDeployError("idle registered machine exists; do not rent")

    pinned = _live_image_tag(site)
    if not pinned:
        raise OverflowDeployError("no succeeded image_tag artifact to pin")

    manifest = site.manifests.order_by("-version").first()
    if manifest is None:
        raise OverflowDeployError("no succeeded image_tag artifact to pin")

    if transport is None:
        from core.ssh import SshTransport

        transport = SshTransport(target)

    deployment = Deployment.objects.create(
        manifest=manifest,
        status=Deployment.Status.QUEUED,
    )
    pipeline.persist_steps(deployment)
    deployment.steps.filter(
        name__in=[DeploymentStep.Name.BUILD, DeploymentStep.Name.DNS],
    ).update(status=DeploymentStep.Status.SKIPPED)

    if not pipeline.begin_deploy(deployment, target=target):
        deployment.status = Deployment.Status.FAILED
        deployment.save(update_fields=["status"])
        raise OverflowDeployError("could not acquire deploy lock")

    pipeline.execute(
        deployment.pk,
        transport=transport,
        dns=dns,
        sleep=sleep,
        cert_issuer=cert_issuer,
    )
    deployment.refresh_from_db()
    if deployment.status != Deployment.Status.SUCCEEDED:
        raise OverflowDeployError("overflow deploy did not succeed")

    body = manifest.body or {}
    port = int(body.get("internal_port") or 20000)
    SiteInstance.objects.create(
        site=site,
        target=target,
        desired_image_tag=pinned,
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.RUNNING,
        internal_port=port,
    )
    return deployment


def _live_image_tag(site):
    from deploys.models import Deployment, DeploymentArtifact

    rows = Deployment.objects.filter(
        manifest__site=site,
        status=Deployment.Status.SUCCEEDED,
    ).order_by("-pk")
    for deployment in rows:
        art = DeploymentArtifact.objects.filter(
            deployment=deployment, kind="image_tag",
        ).first()
        if art is None:
            continue
        tag = (art.content or "").strip()
        if tag:
            return tag
    return None
