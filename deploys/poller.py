"""Git polling: compare branch head to last deployed sha and enqueue deploys.

Beat drives `deploys.tasks.poll_git` on queue `probes` every 1–5 min. There is no
Django webhook — T1 injects `ls_remote(url, ref) -> sha` so tests never hit the
network. `deploys/` still does not import `scanner/`.
"""
import os
import shutil
import subprocess  # nosec B404 — argv-list git ls-remote, never shell=True

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.audit import audit
from core.models import AuditEvent, Site
from core.validators import validate_git_url
from deploys.models import Deployment, Manifest

_GIT_DROP_ENV = (
    "SSH_AUTH_SOCK",
    "SSH_AGENT_PID",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
    "GIT_CONFIG",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_COUNT",
)
_GIT_SSH_COMMAND = (
    "ssh -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none"
)


def _isolated_git_env():
    """Hub git must not use the operator agent, askpass, or ambient gitconfig."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _GIT_DROP_ENV and not key.startswith("GIT_CONFIG_")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = _GIT_SSH_COMMAND
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def git_ls_remote(url, ref):
    """Return the object sha at `ref` on `url`. Argv list, never a shell string."""
    try:
        validate_git_url(url, resolve=True)
    except ValidationError:
        return ""
    git = shutil.which("git")
    if not git:
        return ""
    try:
        result = subprocess.run(  # nosec B603 — argv list; `--` before url/ref
            [
                git,
                "-c", "http.followRedirects=false",
                "-c", "credential.helper=",
                "ls-remote", "--", url, ref,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=_isolated_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    return result.stdout.split()[0]


def cron_in_window(cron, now):
    """True when `now` matches a 5-field cron (min hour day month weekday)."""
    if not cron or not str(cron).strip():
        return False
    fields = str(cron).split()
    if len(fields) != 5:
        return False
    minute, hour, day, month, weekday = fields
    dow = (now.weekday() + 1) % 7
    return (
        _cron_field(minute, now.minute)
        and _cron_field(hour, now.hour)
        and _cron_field(day, now.day)
        and _cron_field(month, now.month)
        and _cron_field(weekday, dow)
    )


def _cron_field(spec, value):
    try:
        for part in spec.split(","):
            if part == "*":
                return True
            if part.startswith("*/"):
                step = int(part[2:])
                if step > 0 and value % step == 0:
                    return True
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                if int(start) <= value <= int(end):
                    return True
                continue
            if int(part) == value:
                return True
    except ValueError:
        return False
    return False


def _last_deployed_sha(site):
    row = (
        Deployment.objects.filter(
            manifest__site=site,
            status=Deployment.Status.SUCCEEDED,
        )
        .select_related("manifest")
        .order_by("-pk")
        .first()
    )
    if row is None:
        return ""
    return (row.manifest.body or {}).get("git_sha") or ""


def _latest_manifest(site):
    return site.manifests.order_by("-version").first()


def _enqueue(site, sha, latest):
    body = dict(latest.body or {})
    body["git_sha"] = sha
    manifest = Manifest.objects.create(
        site=site,
        version=latest.version + 1,
        schema_version=latest.schema_version,
        body=body,
        scan_report_hash=latest.scan_report_hash,
        scanned_at=latest.scanned_at,
        created_by=latest.created_by,
    )
    return Deployment.objects.create(manifest=manifest, status=Deployment.Status.QUEUED)


def _queued_for_sha(site, sha):
    for dep in Deployment.objects.filter(
        manifest__site=site,
        status=Deployment.Status.QUEUED,
    ).select_related("manifest"):
        if (dep.manifest.body or {}).get("git_sha") == sha:
            return dep
    return None


def _promote_waiting(site, sha, *, in_window, now, delay):
    """Delay a parked windowed row once the cron window opens. No new Manifest."""
    if site.deploy_policy != Site.DeployPolicy.WINDOWED:
        return
    if not in_window(site.deploy_window_cron, now):
        return
    dep = _queued_for_sha(site, sha)
    if dep is None or dep.last_heartbeat is not None:
        return
    waiting = AuditEvent.objects.filter(
        action="deploy-waiting",
        object_type="Deployment",
        object_id=str(dep.pk),
    ).exists()
    if not waiting:
        return
    Deployment.objects.filter(
        pk=dep.pk, status=Deployment.Status.QUEUED,
    ).update(last_heartbeat=now)
    delay(dep.pk)


def enqueue_git_push(git_url, ref, sha, *, now=None, in_window=None):
    """Wake the git poller for matching Projects. Planted sha is not the head."""
    validate_git_url(git_url, resolve=False)
    hint_url, hint_ref = git_url, ref

    def lookup(url, remote_ref):
        if url == hint_url and remote_ref == hint_ref:
            return git_ls_remote(url, remote_ref)
        return ""

    poll(ls_remote=lookup, now=now, in_window=in_window)


def poll(*, ls_remote=None, now=None, in_window=None):
    """For each Site with a Project git_url, enqueue when the branch head moved."""
    if ls_remote is None:
        ls_remote = git_ls_remote
    if in_window is None:
        in_window = cron_in_window
    if now is None:
        now = timezone.now()

    from deploys.tasks import enqueue_run_deploy

    sites = Site.objects.select_related("project").exclude(project__git_url="")
    for site in sites:
        project = site.project
        try:
            validate_git_url(
                project.git_url, resolve=ls_remote is git_ls_remote,
            )
        except ValidationError as exc:
            code = ""
            if getattr(exc, "error_list", None):
                code = getattr(exc.error_list[0], "code", "") or ""
            audit(
                "git-url-blocked", site, source="celery",
                code=code or "invalid",
            )
            continue
        sha = ls_remote(project.git_url, project.git_ref)
        if not sha:
            continue
        latest = _latest_manifest(site)
        if latest is None:
            continue
        latest_sha = (latest.body or {}).get("git_sha") or ""
        if sha == _last_deployed_sha(site):
            continue
        if sha == latest_sha:
            _promote_waiting(
                site, sha, in_window=in_window, now=now, delay=enqueue_run_deploy,
            )
            continue
        if site.deploy_policy == Site.DeployPolicy.CONFIRM:
            audit("deploy-confirm-required", site, source="celery", git_sha=sha)
            continue
        if (
            site.deploy_policy == Site.DeployPolicy.WINDOWED
            and not in_window(site.deploy_window_cron, now)
        ):
            deployment = _enqueue(site, sha, latest)
            audit("deploy-waiting", deployment, source="celery", git_sha=sha)
            continue
        deployment = _enqueue(site, sha, latest)
        enqueue_run_deploy(deployment.pk)
