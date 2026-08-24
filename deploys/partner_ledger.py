"""Django ORM adapter for core.partner_deploys.PartnerDeployStore."""
from core.partner_deploys import PartnerDeployStore
from deploys.models import Deployment, Manifest


class DjangoPartnerDeployStore(PartnerDeployStore):
    def get_deployment(self, partner, deployment_id):
        return Deployment.objects.filter(
            pk=deployment_id,
            manifest__site__partner_site__partner=partner,
        ).first()

    def find_by_job_id(self, partner, job_id):
        if not job_id:
            return None
        qs = Deployment.objects.filter(
            manifest__site__partner_site__partner=partner,
        ).select_related("manifest", "manifest__site")
        for dep in qs:
            if (dep.manifest.body or {}).get("partner_job_id") == job_id:
                return dep
        return None

    def create_queued(self, site, body):
        last = site.manifests.order_by("-version").values_list(
            "version", flat=True,
        ).first()
        version = (last or 0) + 1
        manifest = Manifest.objects.create(
            site=site, version=version, body=body,
        )
        deployment = Deployment.objects.create(
            manifest=manifest, status=Deployment.Status.QUEUED,
        )
        return manifest, deployment

    def count_since(self, partner, since, site=None):
        qs = Deployment.objects.filter(manifest__created_at__gte=since)
        if site is not None:
            qs = qs.filter(manifest__site=site)
        else:
            qs = qs.filter(manifest__site__partner_site__partner=partner)
        return qs.count()
