"""Git polling Beat job — no webhook ingress (PIPE-M2-GIT-POLLING)."""
import pytest
from django.conf import settings
from django.urls import get_resolver

from core.models import Project, Site
from deploys.models import Deployment, Manifest

pytestmark = pytest.mark.django_db

OLD_SHA = "aaa111old"
NEW_SHA = "bbb222new"

WEBHOOK_NEEDLES = (
    "github", "webhook", "gitea", "deploy-hook",
    # §7 C3: Hub urlpatterns gain zero /api/partner, /partner/v1, or /mcp.
    "api/partner", "/mcp", "partner/v1",
)

TRIGGER_PATHS = (
    "/hooks/github",
    "/hooks/github/",
    "/api/github/webhook",
    "/api/github/webhook/",
    "/deploy",
    "/deploy/",
    "/webhooks/github",
    "/gitea/webhook",
    "/deploy-hook",
    "/hooks/git-push",
    "/partner/v1/git-push",
    "/api/partner",
    "/api/partner/",
    "/api/partner/v1/sites",
    "/partner/v1/sites",
    "/mcp",
    "/mcp/",
)


def _git_site(*, slug, git_sha=OLD_SHA, succeeded=True):
    project = Project.objects.create(
        name=slug,
        slug=f"p-{slug}",
        git_url="https://github.com/o/r.git",
        git_ref="main",
    )
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(project=project, name=slug,
                               dns_zone=default_dns_zone())
    manifest = Manifest.objects.create(
        site=site, version=1, body={"git_sha": git_sha, "keep": "yes"},
    )
    if succeeded:
        Deployment.objects.create(
            manifest=manifest, status=Deployment.Status.SUCCEEDED,
        )
    return site


def _patch_delay(monkeypatch):
    from deploys.tasks import run_deploy

    queued = []
    monkeypatch.setattr(
        run_deploy, "delay",
        lambda pk, envelope=None, **kwargs: queued.append(pk),
    )
    return queued


def _route_strings(patterns=None, prefix=""):
    if patterns is None:
        patterns = get_resolver().url_patterns
    found = []
    for pattern in patterns:
        inner = pattern.pattern
        piece = getattr(inner, "_route", None)
        if piece is None:
            piece = str(inner)
        route = f"{prefix}{piece}"
        name = getattr(pattern, "name", None) or ""
        found.append(f"{route} {name}".lower())
        nested = getattr(pattern, "url_patterns", None)
        if nested is not None:
            found.extend(_route_strings(nested, route))
    return found


@pytest.mark.req("PIPE-M2-GIT-POLLING")
def test_new_head_enqueues_deploy(monkeypatch):
    """A moved branch head materializes Manifest N+1 and delays run_deploy with an id.

    What would make this fail: skipping the enqueue, rewriting Manifest v1 in place,
    or putting git bytes on the broker instead of a deployment id.
    """
    from deploys.poller import poll
    from deploys.tasks import poll_git

    queued = _patch_delay(monkeypatch)
    site = _git_site(slug="new-head")
    seen = []

    def ls_remote(url, ref):
        seen.append((url, ref))
        return NEW_SHA

    poll(ls_remote=ls_remote)

    assert seen == [("https://github.com/o/r.git", "main")]
    assert queued == [Deployment.objects.exclude(
        status=Deployment.Status.SUCCEEDED,
    ).get().pk]
    created = Deployment.objects.get(pk=queued[0])
    assert created.status == Deployment.Status.QUEUED
    assert created.manifest.version == 2
    assert created.manifest.body["git_sha"] == NEW_SHA
    assert created.manifest.body["keep"] == "yes"
    v1 = Manifest.objects.get(site=site, version=1)
    assert v1.body["git_sha"] == OLD_SHA

    from deploys.tasks import dispatch_poll_git

    beat = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert dispatch_poll_git.name in beat
    schedule = next(
        entry["schedule"]
        for entry in settings.CELERY_BEAT_SCHEDULE.values()
        if entry["task"] == dispatch_poll_git.name
    )
    assert 60 <= float(schedule) <= 300
    assert settings.CELERY_TASK_ROUTES[poll_git.name]["queue"] == "control"


@pytest.mark.req("PIPE-M2-GIT-POLLING")
def test_same_head_does_not_enqueue(monkeypatch):
    """Polling the same sha twice does not create a second Deployment or delay again.

    What would make this fail: treating every Beat tick as new, or comparing only
    succeeded rows so a just-queued sha is delayed twice.
    """
    from deploys.poller import poll

    queued = _patch_delay(monkeypatch)
    _git_site(slug="same-head")

    poll(ls_remote=lambda url, ref: NEW_SHA)
    assert len(queued) == 1
    after_first = Deployment.objects.count()

    poll(ls_remote=lambda url, ref: NEW_SHA)
    assert queued == queued[:1]
    assert Deployment.objects.count() == after_first


@pytest.mark.req("PIPE-M2-GIT-POLLING")
def test_no_webhook_url_route_exists():
    """urlpatterns contain no github/webhook/gitea/deploy-hook path.

    What would make this fail: adding a Django webhook view, even behind auth.
    """
    offenders = [
        route for route in _route_strings()
        if any(needle in route for needle in WEBHOOK_NEEDLES)
    ]
    assert offenders == []


@pytest.mark.req("PIPE-M2-GIT-POLLING")
def test_non_tailnet_cannot_hit_a_deploy_trigger_route(client):
    """There is no inbound deploy-trigger route: candidate paths 404.

    What would make this fail: a 200/201/302 webhook or /deploy trigger reachable
    from a non-tailnet source. Phase 2 proof is zero inbound, not Tailscale middleware.
    """
    for path in TRIGGER_PATHS:
        response = client.get(path)
        assert response.status_code == 404, f"{path} returned {response.status_code}"
        response = client.post(path)
        assert response.status_code == 404, f"POST {path} returned {response.status_code}"
