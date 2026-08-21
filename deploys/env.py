"""Per-site env: names listed, values write-only through vault, apply skips build/ship.

Add/edit/delete sets Site.config_stale. Apply materializes Manifest N+1 with an
updated env_bundle_ref, keeps git_sha so image_tag() is the existing tag, marks
build+ship skipped, and runs the remaining steps.
"""
import copy
import json

from django.db import transaction

from vault import service as vault_service
from vault.models import Secret

SITE_OWNER = "site"


@transaction.atomic
def put_env(site, mapping):
    """Replace the site-owned env bundle. Values never land on Site or Manifest.body."""
    mapping = _clean_mapping(mapping)
    previous = _site_secret(site)
    vault_service.put(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type=SITE_OWNER,
        owner_id=str(site.pk),
        plaintext=json.dumps(mapping, sort_keys=True).encode("utf-8"),
    )
    if previous is not None:
        previous.delete()
    site.config_stale = True
    site.save(update_fields=["config_stale"])


def list_env_names(site):
    """Names only — decrypts the current bundle for keys, never returns values."""
    return sorted(_desired_mapping(site))


def merge_env(site, mapping):
    """Add/edit keys on the current site bundle; still marks config_stale."""
    merged = dict(_desired_mapping(site))
    merged.update(_clean_mapping(mapping))
    put_env(site, merged)


def apply_env(site, *, transport=None, dns=None):
    """Enqueue a same-image deploy (build+ship skipped) and clear config_stale on success."""
    from deploys.models import Deployment, DeploymentStep, Manifest
    from deploys.pipeline import execute, persist_steps

    with transaction.atomic():
        latest = site.manifests.order_by("-version").first()
        if latest is None:
            raise ValueError("no manifest to apply")
        mapping = _desired_mapping(site, latest)
        version = latest.version + 1
        body = copy.deepcopy(latest.body or {})
        bundle = vault_service.put(
            kind=Secret.Kind.ENV_BUNDLE,
            owner_type="manifest",
            owner_id=f"{site.pk}:v{version}",
            plaintext=json.dumps(mapping, sort_keys=True).encode("utf-8"),
        )
        body["env_bundle_ref"] = bundle.pk
        body["env_names"] = sorted(mapping)
        manifest = Manifest.objects.create(
            site=site,
            version=version,
            schema_version=latest.schema_version,
            body=body,
            scan_report_hash=latest.scan_report_hash,
            scanned_at=latest.scanned_at,
        )
        deployment = Deployment.objects.create(
            manifest=manifest,
            status=Deployment.Status.QUEUED,
        )
        persist_steps(deployment)
        deployment.steps.filter(
            name__in=[DeploymentStep.Name.BUILD, DeploymentStep.Name.SHIP],
        ).update(status=DeploymentStep.Status.SKIPPED)

    if transport is not None:
        execute(deployment.pk, transport=transport, dns=dns)
    else:
        from deploys.tasks import run_deploy

        run_deploy.delay(deployment.pk)

    deployment.refresh_from_db()
    if deployment.status == Deployment.Status.SUCCEEDED:
        site.config_stale = False
        site.save(update_fields=["config_stale"])
    return deployment


def _site_secret(site):
    return Secret.objects.filter(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type=SITE_OWNER,
        owner_id=str(site.pk),
    ).first()


def _desired_mapping(site, latest=None):
    secret = _site_secret(site)
    if secret is not None:
        return _loads(secret, reason=f"site env {site.pk}")
    if latest is None:
        latest = site.manifests.order_by("-version").first()
    ref = (latest.body or {}).get("env_bundle_ref") if latest else None
    if not ref:
        return {}
    try:
        secret = Secret.objects.get(pk=ref)
    except Secret.DoesNotExist:
        return {}
    return _loads(secret, reason=f"site env {site.pk}")


def _loads(secret, *, reason):
    raw = vault_service.get(secret, reason=reason)
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return _clean_mapping(data)


def _clean_mapping(mapping):
    if mapping is None:
        return {}
    if not isinstance(mapping, dict):
        raise TypeError("env mapping must be a dict")
    cleaned = {}
    for key, value in mapping.items():
        name = str(key).strip()
        if not name:
            continue
        cleaned[name] = "" if value is None else str(value)
    return cleaned
