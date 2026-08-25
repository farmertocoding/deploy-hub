"""T1 overflow same-image deploy + join traffic.

refuse_if_attack first, then ACCEPTED scale-out-proposal:{pk}, then ephemeral
READY non-primary. Deploy: idle-pick miss, pin live tag, skip BUILD+DNS, SHIP.
Join: RUNNING SiteInstance, DNS A next to primary or tunnel replica sibling.
Gate OverflowDeployError does not raise_alert, _retract, write Finding, or
write CheckRun. Deploy execute is in-process; do not queue the worker.
"""
import ipaddress

from django.utils import timezone

from core.overflow_deploys import OverflowDeployError
from scaling.attack_gate import AttackRefuse, PartnerOverflowRefuse, refuse_if_attack
from scaling.constants import FIX_ACTION
from scaling.destination import pick_overflow_home

_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
TUNNEL_UNCONFIGURED = "tunnel replica is not configured"
COPY_NOT_RUNNING = "overflow copy is not running"
LOCK_BUSY = "could not acquire deploy lock"
EQUAL_IPV4 = "overflow origin IPv4 matches primary"
NEED_ORIGIN = "overflow join needs origin IPv4s or a tunnel-mode home"


def overflow_copy_thunk(*args, **kwargs):
    """Port thunk: look up deploy_overflow_copy at call time (HTTP inject)."""
    from deploys import overflow as overflow_mod

    return overflow_mod.deploy_overflow_copy(*args, **kwargs)


def overflow_join_thunk(*args, **kwargs):
    """Port thunk: look up join_overflow_traffic at call time (HTTP inject)."""
    from deploys import overflow as overflow_mod

    return overflow_mod.join_overflow_traffic(*args, **kwargs)


def _joinable_ipv4(host):
    """Public unicast IPv4, plus TEST-NET documentation ranges used in T1.

    Do not use IPv4Address.is_private / is_global as the allow — this
    interpreter treats 203.0.113.0/24 as private.
    """
    try:
        addr = ipaddress.IPv4Address(str(host).strip())
    except ValueError:
        return None
    if (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
    ):
        return None
    if any(addr in net for net in _RFC1918) or addr in _CGNAT:
        return None
    return str(addr)


def _tunnel_home(site):
    target = site.primary_target
    if target is None:
        return False
    payload = target.collect_payload or {}
    from core.models import Target

    return target.kind == Target.Kind.SSH and payload.get("tunnel") is True


def _start_cloudflared_replica(site, target, transport=None):
    """Refuse-closed: no Hub-vaulted tunnel JWT (B5). No Transport."""
    raise OverflowDeployError(TUNNEL_UNCONFIGURED)


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


def join_overflow_traffic(
    site, target, *, dns=None, replica=None, transport=None,
):
    """Join a running overflow copy: DNS A next to primary, or tunnel replica."""
    try:
        refuse_if_attack(site)
    except (AttackRefuse, PartnerOverflowRefuse) as exc:
        raise OverflowDeployError(str(exc)) from exc

    from core import locks
    from core.models import Finding, Site, SiteInstance, Target
    from deploys.steps import ensure_dns

    row = Finding.objects.filter(
        fingerprint=f"scale-out-proposal:{site.pk}",
    ).first()
    if row is None or row.state != Finding.State.ACCEPTED:
        raise OverflowDeployError(FIX_ACTION)

    if site.exposure == Site.Exposure.MESH_ONLY:
        raise OverflowDeployError(NEED_ORIGIN)

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

    inst = SiteInstance.objects.filter(site=site, target=target).first()
    if inst is None or inst.observed_state != SiteInstance.ObservedState.RUNNING:
        raise OverflowDeployError(COPY_NOT_RUNNING)

    holder = f"overflow-join:{site.pk}"
    if locks.acquire("site", site.pk, "deploy", holder) is None:
        raise OverflowDeployError(LOCK_BUSY)
    try:
        if _tunnel_home(site):
            fn = replica if replica is not None else _start_cloudflared_replica
            fn(site, target, transport)
            return {"target": target.pk, "joined": "tunnel"}

        primary = site.primary_target
        primary_ip = _joinable_ipv4(primary.host if primary is not None else "")
        overflow_ip = _joinable_ipv4(target.host)
        if primary_ip is None or overflow_ip is None:
            raise OverflowDeployError(NEED_ORIGIN)
        if primary_ip == overflow_ip:
            raise OverflowDeployError(EQUAL_IPV4)
        if site.exposure != Site.Exposure.PUBLIC:
            raise OverflowDeployError(NEED_ORIGIN)

        if dns is None:
            from providers.registry import ScopeError, dns_provider_for

            if site.dns_zone_id is None:
                raise OverflowDeployError("could not construct dns provider")
            try:
                dns = dns_provider_for(site.dns_zone)
            except ScopeError as exc:
                raise OverflowDeployError("could not construct dns provider") from exc

        ensure_dns({
            "site": site,
            "dns": dns,
            "dns_zone": site.dns_zone,
            "zone": site.dns_zone,
            "domain": site.domain,
            "dns_values": [primary_ip, overflow_ip],
            "dns_proxied": site.proxied,
        })
        return {
            "target": target.pk,
            "joined": "dns",
            "name": site.domain,
            "values": [primary_ip, overflow_ip],
        }
    finally:
        locks.release("site", site.pk, "deploy", holder=holder)
