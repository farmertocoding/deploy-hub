"""Hub re-validator + partner-job materialize. Isolation without Site.tier.

Does not import intake. The partner router maps K3 actions to partner_job.*
handlers — never ACTION_TIERS T1/T2 internal ids. Querysets filter on Partner.
"""
import json
from urllib.parse import urlparse

from django.conf import settings

from core.partner_templates import (
    SOURCE_DIR,
    TEMPLATE_REF,
    fixture_archive,
    load_pinned_digest,
)

# Keys are intake partner-job actions / K3 families. Values are Hub handlers.
# Standing K6 test fails if either side is an ACTION_TIERS T1/T2 internal id.
PARTNER_ROUTER = {
    "site.create": "partner_job.create_site",
    "deployment.create": "partner_job.create_deployment",
    "deployment.get": "partner_job.get_deployment",
    "domain.create": "partner_job.create_domain",
    "domain.get": "partner_job.get_domain",
    "site.delete": "partner_job.delete_site",
    "domain.delete": "partner_job.delete_domain",
}

_SOURCE_REASONS = (
    ("dockerfile", "dockerfile"),
    ("Dockerfile", "dockerfile"),
    ("dockerfile_content", "dockerfile"),
    ("docker_file", "dockerfile"),
    ("build", "build"),
    ("build_context", "build"),
    ("jobs_image", "jobs_image"),
    ("git_url", "git-source"),
    ("git_source", "git-source"),
    ("source_git", "git-source"),
)


class PartnerRefuse(RuntimeError):
    """Isolation / template refuse. Not IDOR — that is PartnerNotFound (404)."""

    status = 403

    def __init__(self, reason, message=""):
        self.reason = reason
        super().__init__(message or reason)


class PartnerNotFound(RuntimeError):
    """Cross-partner or missing id. Always 404, never 403."""

    status = 404

    def __init__(self, message="not found"):
        super().__init__(message)


class MaterializeResult:
    def __init__(self, site, partner_site, manifest, deployment):
        self.site = site
        self.partner_site = partner_site
        self.manifest = manifest
        self.deployment = deployment


def partner_sites_qs(partner):
    from core.models import Site

    return Site.objects.filter(partner_site__partner=partner)


def get_partner_site(partner, site_id):
    from core.models import PartnerSite

    row = (
        PartnerSite.objects.filter(partner=partner, site_id=site_id)
        .select_related("site")
        .first()
    )
    if row is None:
        raise PartnerNotFound()
    return row


def get_partner_deployment(partner, deployment_id):
    from deploys.models import Deployment

    dep = Deployment.objects.filter(
        pk=deployment_id,
        manifest__site__partner_site__partner=partner,
    ).first()
    if dep is None:
        raise PartnerNotFound()
    return dep


def refuse_scheduled_job(site, action="create"):
    from core.models import PartnerSite

    if PartnerSite.objects.filter(site=site).exists():
        raise PartnerRefuse(
            "scheduled-job",
            "scheduled-job create/edit is prohibited on a PartnerSite",
        )
    return None


def materialize(partner, job, *, transport=None, registry=None, now=None):
    """Turn a validated partner-job into an ordinary Deployment + PartnerSite."""
    if not getattr(settings, "PARTNER_API_ENABLED", False):
        return None

    from core.partner_verify import evaluate_quotas

    payload = _payload(job)
    _refuse_source(payload)
    digest = _require_template(payload)
    target = _destination(partner, payload)
    _refuse_hub_host(target)
    _refuse_cohost(target)
    _require_tunnel(target)
    domain = _domain(partner, payload)
    _refuse_partner_base(domain)

    existing = _existing_deployment(partner, job.get("id"))
    if existing is not None:
        _probe_only(existing, digest, transport=transport, registry=registry)
        return existing

    method = job.get("method") or "POST"
    path = job.get("path") or "/partner/v1/sites"
    body = job.get("body") or payload
    decision = evaluate_quotas(
        partner, method, path, now=now, body=body,
    )
    if decision.refused:
        raise PartnerRefuse(decision.reason or "quota")

    result = _create(partner, job, payload, target, domain, digest, now=now)
    _ship(digest, target, transport=transport, registry=registry)
    return result


def _payload(job):
    payload = dict(job.get("payload") or {})
    body = job.get("body")
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    if isinstance(body, str) and body.strip():
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {}
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                payload.setdefault(key, value)
    return payload


def _refuse_source(payload):
    source_kind = str(payload.get("source_kind") or "").strip().lower()
    if source_kind == "git":
        raise PartnerRefuse("git-source")
    for key, reason in _SOURCE_REASONS:
        if key not in payload:
            continue
        value = payload.get(key)
        if value in (None, "", False):
            continue
        raise PartnerRefuse(reason)


def _require_template(payload):
    pin = load_pinned_digest()
    ref = payload.get("template_ref")
    if ref not in (None, "", TEMPLATE_REF):
        raise PartnerRefuse("unconstrained-image")
    image = payload.get("image")
    if image not in (None, "", TEMPLATE_REF, f"{TEMPLATE_REF}@{pin}"):
        raise PartnerRefuse("unconstrained-image")
    given = payload.get("image_digest")
    if given not in (None, "", pin):
        raise PartnerRefuse("unconstrained-image")
    return pin


def _destination(partner, payload):
    from core.models import Target

    order = [int(pk) for pk in (partner.destination_order or [])]
    if not order:
        raise PartnerRefuse("empty-destination-order")
    specified = payload.get("target_id") or payload.get("target_pk")
    if specified is not None and int(specified) not in order:
        raise PartnerRefuse("destination-not-ranked")
    pk = int(specified) if specified is not None else order[0]
    target = Target.objects.filter(pk=pk).first()
    if target is None:
        raise PartnerRefuse("destination-missing")
    if target.pk not in order:
        raise PartnerRefuse("destination-not-ranked")
    return target


def _hub_hostname():
    raw = (getattr(settings, "HUB_PUBLIC_URL", "") or "").strip()
    if not raw:
        return ""
    return (urlparse(raw).hostname or "").casefold()


def _refuse_hub_host(target):
    hostname = _hub_hostname()
    if hostname and (target.host or "").casefold() == hostname:
        raise PartnerRefuse("hub-host")


def _hosted_site_ids(target):
    from core.models import Site, SiteInstance

    ids = set(
        Site.objects.filter(primary_target=target).values_list("pk", flat=True),
    )
    ids.update(
        SiteInstance.objects.filter(target=target).values_list("site_id", flat=True),
    )
    return ids


def _refuse_cohost(target):
    from core.models import PartnerSite

    hosted = _hosted_site_ids(target)
    if not hosted:
        return
    partnered = set(
        PartnerSite.objects.filter(site_id__in=hosted).values_list("site_id", flat=True),
    )
    if hosted - partnered:
        raise PartnerRefuse("non-partner-cohost")


def _require_tunnel(target):
    from core.findings import finding
    from core.models import Target

    if target.kind != Target.Kind.SSH:
        return
    collected = target.collect_payload or {}
    if collected.get("tunnel") is True:
        return
    finding(
        "core.partner_jobs",
        f"partner-tunnel-required:{target.pk}",
        severity="p2",
        entity=f"target:{target.pk}",
        title="Own-server partner destination requires a tunnel",
        body=(
            "This partner-tier target is kind=ssh and collect_payload.tunnel "
            "is not true. Partner sites refuse until Tunnel mode is on so the "
            "operator IP is not the origin for someone else's content."
        ),
        fix_action="Set collect_payload.tunnel true on this target, then retry.",
    )
    raise PartnerRefuse("tunnel-required")


def _domain(partner, payload):
    explicit = (payload.get("domain") or payload.get("hostname") or "").strip()
    if explicit:
        return explicit.casefold()
    subdomain = (payload.get("subdomain") or payload.get("tenant_ref") or "").strip()
    if not subdomain:
        return ""
    return f"{subdomain}.apps.invalid"


def _refuse_partner_base(domain):
    from core.models import PartnerSite, Site

    if not domain:
        return
    needle = domain.casefold()
    partnered = PartnerSite.objects.values_list("site_id", flat=True)
    for site in Site.objects.exclude(pk__in=partnered):
        other = (site.domain or "").casefold()
        if not other:
            continue
        if other == needle or needle.endswith("." + other) or other.endswith("." + needle):
            raise PartnerRefuse("partner-base")


def _existing_deployment(partner, job_id):
    from deploys.models import Deployment

    if not job_id:
        return None
    qs = Deployment.objects.filter(
        manifest__site__partner_site__partner=partner,
    ).select_related("manifest", "manifest__site")
    for dep in qs:
        if (dep.manifest.body or {}).get("partner_job_id") == job_id:
            site = dep.manifest.site
            return MaterializeResult(site, site.partner_site, dep.manifest, dep)
    return None


def _probe_only(result, digest, *, transport, registry):
    if transport is not None:
        transport.probe(["docker", "image", "inspect", digest])
    if registry is not None:
        registry.pull_spec(digest, target=result.site.primary_target)


def _require_quota(partner, method, path, *, now=None, body=None):
    """Raise PartnerRefuse when Hub evaluate_quotas refuses this insert."""
    from core.partner_verify import evaluate_quotas

    decision = evaluate_quotas(partner, method, path, now=now, body=body)
    if decision.refused:
        raise PartnerRefuse(decision.reason or "quota")


def _create(partner, job, payload, target, domain, digest, *, now=None):
    from core.models import PartnerSite, Project, Site
    from deploys.models import Deployment, Manifest

    tenant_ref = str(payload.get("tenant_ref") or "").strip() or "default"
    binding = (
        PartnerSite.objects.filter(partner=partner, tenant_ref=tenant_ref)
        .select_related("site")
        .first()
    )
    body = job.get("body") or payload
    # Minting a PartnerSite pays max_sites/fleet even when path is deploy-create.
    if binding is None:
        _require_quota(
            partner, "POST", "/partner/v1/sites", now=now, body=body,
        )
        site_token = tenant_ref
    else:
        site_token = binding.site_id
    _require_quota(
        partner, "POST", f"/partner/v1/sites/{site_token}/deployments",
        now=now, body=body,
    )
    if binding is None:
        slug = f"p-{partner.slug}-{tenant_ref}"[:128]
        project = Project.objects.create(
            name=slug,
            slug=slug,
            source_kind=Project.Source.LOCAL_PATH,
            local_path=str(SOURCE_DIR),
            git_url="",
        )
        site = Site.objects.create(
            project=project,
            name=slug,
            domain=domain,
            exposure=Site.Exposure.MESH_ONLY,
            primary_target=target,
        )
        binding = PartnerSite.objects.create(
            partner=partner, site=site, tenant_ref=tenant_ref,
        )
    else:
        site = binding.site
    last = site.manifests.order_by("-version").values_list("version", flat=True).first()
    version = (last or 0) + 1
    manifest = Manifest.objects.create(
        site=site,
        version=version,
        body={
            "schema_version": 1,
            "runtime": "static",
            "image_digest": digest,
            "template_ref": TEMPLATE_REF,
            "partner_job_id": job.get("id"),
            "ship_mode": "load",
        },
    )
    deployment = Deployment.objects.create(
        manifest=manifest, status=Deployment.Status.QUEUED,
    )
    return MaterializeResult(site, binding, manifest, deployment)


def _ship(digest, target, *, transport, registry):
    from core.hubfs import hub_join, ssh_user_from

    archive = fixture_archive()
    if registry is not None and digest not in registry.images:
        registry.push(digest, archive)
    if transport is None:
        return
    inspect = transport.probe(["docker", "image", "inspect", digest])
    stdout = inspect.stdout or ""
    if inspect.ok and digest in stdout:
        return
    remote = hub_join(
        "partner-templates", f"{TEMPLATE_REF}.tar",
        ssh_user=ssh_user_from(target),
    )
    transport.put(archive, remote)
    transport.run(["docker", "load", "-i", remote])
