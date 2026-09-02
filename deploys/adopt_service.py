"""Queue and execute live Site adoption (Wave 2).

HTTP callers use start_adopt / cancel_adopt. Workers call execute_adopt /
execute_cancel. Celery payloads are IDs plus an optional path scalar.
CheckRun.results stay the closed S2 schema.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core.models import CheckRun, Site, SiteVolume
from deploys.adopt_flow import AdoptRefused, adopt_flow, cleanup
from deploys.seams import DeploySeamRefused

MAX_LIVE_COMPOSE_PATH = 4096
_CANCELLABLE = frozenset({"", "temp_dns", "verify"})
_POST_FLIP = frozenset({"flip", "decommission"})
_ACTIVE = frozenset({"", "temp_dns", "verify", "flip", "decommission"})


class AdoptHttpError(Exception):
    def __init__(self, detail, status):
        self.detail = detail
        self.status = status
        super().__init__(detail)


@dataclass
class AdoptOperation:
    run: CheckRun
    queued: bool

    @property
    def http_status(self):
        return 202 if self.queued else 200


def find_adopt_run(site):
    for row in CheckRun.objects.filter(kind=CheckRun.Kind.ADOPT).order_by("-pk"):
        if row.results.get("site_id") == site.pk:
            return row
    return None


def adopt_state_for_site(site):
    """Project-list payload. Null when this Site has never had an adopt run."""
    run = find_adopt_run(site)
    if run is None:
        return None
    volumes = list(
        SiteVolume.objects.filter(site=site).order_by("name").values_list("name", flat=True)
    )
    results = run.results or {}
    return {
        "stage": results.get("stage") or "",
        "temp_name": results.get("temp_name") or "",
        "status": run.status,
        "checkrun_id": run.pk,
        "volumes": volumes,
    }


def start_adopt(site, *, live_compose_path=None):
    path = _clean_path(live_compose_path)
    if site.primary_target_id is None:
        raise AdoptHttpError("adopt refuses without a primary_target", 409)
    _refuse_unconfigured_seams(site)
    with transaction.atomic():
        run = find_adopt_run(site)
        if run is not None and run.status == CheckRun.Status.RUNNING:
            stage = (run.results or {}).get("stage") or ""
            if stage in _ACTIVE:
                return AdoptOperation(run, queued=False)
        if run is not None and run.status == CheckRun.Status.FAILED:
            stage = (run.results or {}).get("stage") or ""
            if stage in _CANCELLABLE:
                run.status = CheckRun.Status.RUNNING
                run.finished = None
                run.save(update_fields=["status", "finished"])
                _queue_start(site.pk, run.pk, path)
                return AdoptOperation(run, queued=True)
        run = CheckRun.objects.create(
            kind=CheckRun.Kind.ADOPT,
            status=CheckRun.Status.RUNNING,
            started=timezone.now(),
            results={
                "schema_version": 1,
                "site_id": site.pk,
                "temp_name": "",
                "stage": "",
                "started_at": timezone.now().isoformat(),
            },
        )
    _queue_start(site.pk, run.pk, path)
    return AdoptOperation(run, queued=True)


def cancel_adopt(site):
    run = find_adopt_run(site)
    if run is None:
        return None
    stage = (run.results or {}).get("stage") or ""
    if stage in _POST_FLIP and run.status == CheckRun.Status.RUNNING:
        raise AdoptHttpError(
            "cancel refused after production flip; use rollback",
            409,
        )
    if stage == "cleanup" or run.status != CheckRun.Status.RUNNING:
        return AdoptOperation(run, queued=False)
    if stage not in _CANCELLABLE:
        raise AdoptHttpError(
            "cancel refused after production flip; use rollback",
            409,
        )
    _queue_cancel(site.pk, run.pk)
    return AdoptOperation(run, queued=True)


def execute_adopt(site_id, checkrun_id, live_compose_path=None):
    site, run = _load(site_id, checkrun_id)
    if run is None or run.status != CheckRun.Status.RUNNING:
        return
    desired = assemble_adopt_desired(site)
    path = live_compose_path or None
    try:
        adopt_flow(desired, live_compose_path=path)
    except (AdoptRefused, DeploySeamRefused):
        _mark_failed(site)
        raise


def execute_cancel(site_id, checkrun_id):
    site, run = _load(site_id, checkrun_id)
    if run is None:
        return
    stage = (run.results or {}).get("stage") or ""
    if stage in _POST_FLIP:
        return
    desired = assemble_adopt_desired(site)
    cleanup(desired)


def assemble_adopt_desired(site):
    from deploys.adopt_reaper import _reconstruct_dns
    from deploys.pipeline import _default_transport
    from deploys.steps import image_tag

    latest = site.manifests.order_by("-version").first()
    body = (latest.body if latest is not None else {}) or {}
    git_sha = body.get("git_sha") or ("0" * 40)
    prev_pk = None
    if latest is not None:
        prev_pk = latest.deployments.order_by("-pk").values_list("pk", flat=True).first()
    old = f"site-{site.name}-{prev_pk}" if prev_pk else f"site-{site.name}"
    dns = _reconstruct_dns(site)
    return {
        "transport": _default_transport(site),
        "site": site,
        "site_slug": site.name,
        "manifest_body": body,
        "git_sha": git_sha,
        "source_dir": _confined_source_dir(site),
        "image_tag": body.get("image_tag") or image_tag(git_sha, body),
        "old_container": old,
        "dns": dns,
        "zone": site.dns_zone.name if site.dns_zone_id else "",
        "dns_zone": site.dns_zone,
        "domain": site.domain,
        "dns_values": list(body.get("dns_values") or []),
        "poll_interval_s": body.get("poll_interval_s", 1),
        "internal_port": int(body.get("internal_port") or 20000),
        "env_names": list(body.get("env_names") or []),
        "firewall_argv": list(body.get("firewall_argv") or []),
    }


def operation_body(op):
    run = op.run
    results = run.results or {}
    return {
        "checkrun_id": run.pk,
        "site_id": results.get("site_id"),
        "stage": results.get("stage") or "",
        "status": run.status,
        "queued": op.queued,
        "temp_name": results.get("temp_name") or "",
    }


def _clean_path(raw):
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise AdoptHttpError("live_compose_path must be a string", 400)
    if "\x00" in raw or len(raw) > MAX_LIVE_COMPOSE_PATH:
        raise AdoptHttpError("live_compose_path is invalid", 400)
    return raw


def _refuse_unconfigured_seams(site):
    """Presence-only. Does not file Findings (HTTP must not mutate on refuse)."""
    if getattr(site, "exposure", None) == "mesh_only":
        return
    missing = []
    if not site.dns_zone_id:
        missing.append("dns_zone")
    else:
        account = site.dns_zone.account
        if not account.dns_token_ref:
            missing.append("dns_token_ref")
        proxied = bool(getattr(site, "proxied", True))
        if proxied and not account.origin_ca_key_ref:
            missing.append("origin_ca_key_ref")
    if missing:
        raise AdoptHttpError("missing " + ", ".join(missing), 503)


def _confined_source_dir(site):
    raw = getattr(site.project, "local_path", "") or ""
    if not raw:
        return ""
    from core.local_sources import resolve_local_source

    return str(resolve_local_source(raw, require_root=True))


def _queue_start(site_id, checkrun_id, path):
    from deploys.tasks import envelope_for_adopt, run_adopt

    run_adopt.delay(
        site_id, checkrun_id, path or "",
        envelope_for_adopt(site_id, "deploys.tasks.run_adopt"),
    )


def _queue_cancel(site_id, checkrun_id):
    from deploys.tasks import cancel_adopt, envelope_for_adopt

    cancel_adopt.delay(
        site_id, checkrun_id,
        envelope_for_adopt(site_id, "deploys.tasks.cancel_adopt"),
    )


def _load(site_id, checkrun_id):
    try:
        site = Site.objects.select_related(
            "dns_zone", "dns_zone__account", "primary_target", "project",
        ).get(pk=site_id)
    except Site.DoesNotExist:
        return None, None
    try:
        run = CheckRun.objects.get(pk=checkrun_id, kind=CheckRun.Kind.ADOPT)
    except CheckRun.DoesNotExist:
        return site, None
    if run.results.get("site_id") != site.pk:
        return site, None
    return site, run


def _mark_failed(site):
    run = find_adopt_run(site)
    if run is None:
        return
    run.status = CheckRun.Status.FAILED
    run.finished = timezone.now()
    run.save(update_fields=["status", "finished"])
