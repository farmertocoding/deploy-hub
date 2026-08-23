"""M2 git-webhook is a second outbox type on the same Hub poller (D-085).

Fake-plant `{type: git-push}`. Not a public intake or Hub route. No webhook
secret on intake. Hub re-validates via validate_git_url.
"""
import ast
import io
import json
import pathlib
import re

import pytest
from django.conf import settings
from django.urls import get_resolver

from core.models import AuditEvent, Project, Site
from deploys.models import Deployment, Manifest

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
OLD_SHA = "aaa111old"
NEW_SHA = "bbb222new"
GIT_URL = "https://github.com/o/r.git"

INTAKE_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+intake\b", re.M)
BANNED_INTAKE_NEEDLES = (
    "HUB_WEBHOOK_SECRET",
    "GITHUB_WEBHOOK",
    "HUB_INTAKE_HMAC",
    "whsec_",
)

HUB_INBOUND = (
    "/hooks/github",
    "/hooks/github/",
    "/api/github/webhook",
    "/webhooks/github",
    "/gitea/webhook",
    "/hooks/git-push",
    "/partner/v1/git-push",
    "/api/partner",
    "/api/partner/",
    "/api/partner/v1/sites",
    "/partner/v1/sites",
    "/mcp",
    "/mcp/",
)

INTAKE_WEBHOOK_PATHS = (
    ("POST", "/hooks/github"),
    ("POST", "/api/github/webhook"),
    ("POST", "/webhooks/github"),
    ("POST", "/gitea/webhook"),
    ("POST", "/hooks/git-push"),
    ("POST", "/partner/v1/git-push"),
    ("POST", "/partner/v1/webhooks"),
    ("GET", "/hooks/github"),
)


def _git_site(*, slug, git_url=GIT_URL, git_ref="main", git_sha=OLD_SHA):
    from dns_fixtures import default_dns_zone

    project = Project.objects.create(
        name=slug, slug=f"p-{slug}", git_url=git_url, git_ref=git_ref,
    )
    site = Site.objects.create(
        project=project, name=slug, dns_zone=default_dns_zone(),
    )
    manifest = Manifest.objects.create(
        site=site, version=1, body={"git_sha": git_sha, "keep": "yes"},
    )
    Deployment.objects.create(
        manifest=manifest, status=Deployment.Status.SUCCEEDED,
    )
    return site


def _patch_delay(monkeypatch):
    from deploys.tasks import run_deploy

    queued = []
    monkeypatch.setattr(run_deploy, "delay", lambda pk: queued.append(pk))
    return queued


def _boom_ls_remote(monkeypatch):
    from deploys import poller as git_poller

    def boom(url, ref):
        raise AssertionError(f"git ls-remote must not run for a planted hint ({url})")

    monkeypatch.setattr(git_poller, "git_ls_remote", boom)


def _poll(client, monkeypatch, **kwargs):
    from monitor.intake_poll import poll

    _boom_ls_remote(monkeypatch)
    return poll(client=client, jitter=0, sleep=lambda _s: None, **kwargs)


def _wsgi_call(app, method, path, body=b"", headers=None):
    if isinstance(body, dict):
        body = json.dumps(body, separators=(",", ":")).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "intake.test",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(response_headers)
        return lambda chunk: None

    raw = b"".join(app(environ, start_response))
    code = int(captured["status"].split()[0])
    return code, raw


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


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_git_push_outbox_enqueues_deploy(monkeypatch):
    """A Fake-planted git-push hint becomes a queued Deployment via git enqueue.

    What would make this fail: ignoring type git-push, calling git ls-remote
    from the Hub, or writing the sha onto Manifest v1 in place.
    """
    from monitor.intake_poll import FakeIntakeClient

    queued = _patch_delay(monkeypatch)
    site = _git_site(slug="git-push-enq")
    other = _git_site(
        slug="other-repo",
        git_url="https://github.com/o/other.git",
    )
    client = FakeIntakeClient()
    client.plant_git_push(GIT_URL, "main", NEW_SHA, job_id="git-1")

    result = _poll(client, monkeypatch)

    assert result["ok"] is True
    assert queued == [
        Deployment.objects.exclude(status=Deployment.Status.SUCCEEDED)
        .get(manifest__site=site)
        .pk
    ]
    created = Deployment.objects.get(pk=queued[0])
    assert created.status == Deployment.Status.QUEUED
    assert created.manifest.version == 2
    assert created.manifest.body["git_sha"] == NEW_SHA
    assert created.manifest.body["keep"] == "yes"
    assert Deployment.objects.filter(manifest__site=other).count() == 1
    assert "git-1" in client.acked


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_git_push_uses_same_poller_as_partner_job(monkeypatch):
    """git-push and partner-job are one Beat fetch; no second git-webhook task.

    What would make this fail: a dedicated poll_git_webhook Beat entry, a second
    fetch, or processing git-push outside monitor.intake_poll.poll.
    """
    from monitor.intake_poll import BATCH_CAP, FakeIntakeClient, poll
    from monitor.tasks import poll_intake_outbox

    queued = _patch_delay(monkeypatch)
    site = _git_site(slug="same-poller")
    client = FakeIntakeClient()
    client.items.append({"id": "job-partner", "type": "partner-job", "action": "site.create"})
    client.plant_git_push(GIT_URL, "main", NEW_SHA, job_id="job-git")

    _boom_ls_remote(monkeypatch)
    result = poll(client=client, jitter=0, sleep=lambda _s: None)

    assert result["ok"] is True
    assert client.fetch_calls == 1
    assert set(client.acked) == {"job-partner", "job-git"}
    assert queued == [
        Deployment.objects.exclude(status=Deployment.Status.SUCCEEDED)
        .get(manifest__site=site)
        .pk
    ]
    assert BATCH_CAP == 20
    beat = settings.CELERY_BEAT_SCHEDULE
    assert beat["poll-intake-outbox"]["task"] == poll_intake_outbox.name
    assert float(beat["poll-intake-outbox"]["schedule"]) == 10.0
    names = {entry["task"] for entry in beat.values()}
    assert poll_intake_outbox.name in names
    assert not any("git-webhook" in name or "git_webhook" in name for name in names)
    assert not any("git-push" in name or "git_push" in name for name in names)
    src = (REPO / "monitor" / "intake_poll.py").read_text(encoding="utf-8")
    assert INTAKE_IMPORT_RE.search(src) is None
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "intake"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "intake"


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_git_url_goes_through_validate_git_url(monkeypatch):
    """The planted git_url is re-validated even when no Site matches.

    What would make this fail: matching Sites by the untrusted hint without
    calling validate_git_url, or only validating Project.git_url after a match.
    """
    from django.core.exceptions import ValidationError

    from deploys import poller as git_poller
    from monitor.intake_poll import FakeIntakeClient

    queued = _patch_delay(monkeypatch)
    seen = []
    real = git_poller.validate_git_url

    def spy(url, *, resolve=True):
        seen.append({"url": url, "resolve": resolve})
        return real(url, resolve=resolve)

    monkeypatch.setattr(git_poller, "validate_git_url", spy)
    import core.validators as validators

    monkeypatch.setattr(validators, "validate_git_url", spy)

    client = FakeIntakeClient()
    planted = "https://evil.example.test/o/r.git"
    client.plant_git_push(planted, "main", NEW_SHA, job_id="git-validate")
    _poll(client, monkeypatch)
    assert seen, "planted git_url never reached validate_git_url"
    assert any(row["url"] == planted for row in seen)
    assert queued == []
    assert not Deployment.objects.filter(status=Deployment.Status.QUEUED).exists()

    seen.clear()
    blocked = FakeIntakeClient()
    blocked.plant_git_push("https://127.0.0.1/o/r.git", "main", NEW_SHA, job_id="git-loop")
    _git_site(slug="blocked-src")
    _poll(blocked, monkeypatch)
    assert queued == []
    with pytest.raises(ValidationError):
        real("https://127.0.0.1/o/r.git", resolve=False)


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_git_push_is_fake_planted_not_a_public_route():
    """T1 Fake plants git-push; GitHub/Gitea HTTP listeners stay 404.

    What would make this fail: a public /hooks/github that writes the outbox,
    or no plant helper so tests have to POST a webhook.
    """
    from intake.app import make_application
    from intake.fake import FakeIntake

    fake = FakeIntake()
    app = make_application(fake)
    job = fake.plant_git_push(GIT_URL, "main", NEW_SHA)
    assert job["type"] == "git-push"
    assert job["git_url"] == GIT_URL
    assert job["ref"] == "main"
    assert job["sha"] == NEW_SHA
    assert fake.outbox.snapshot() == [job]
    payload = {"ref": "refs/heads/main", "after": NEW_SHA, "repository": {"clone_url": GIT_URL}}
    for method, path in INTAKE_WEBHOOK_PATHS:
        code, raw = _wsgi_call(app, method, path, body=payload)
        assert code == 404, f"{method} {path} → {code}"
        assert b"git-push" not in raw
    assert fake.outbox.snapshot() == [job]


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_intake_public_listener_still_six_k3_routes():
    """Public intake listener is still the six K3 families; git-push is not a 7th.

    What would make this fail: mounting /hooks/github or /partner/v1/git-push
    on application, or shrinking PUBLIC_ROUTE_FAMILIES.
    """
    from intake.app import PUBLIC_ROUTE_FAMILIES, make_application

    assert set(PUBLIC_ROUTE_FAMILIES) == {
        ("POST", "/partner/v1/sites"),
        ("POST", "/partner/v1/sites/{id}/deployments"),
        ("GET", "/partner/v1/deployments/{id}"),
        ("POST", "/partner/v1/sites/{id}/domains"),
        ("GET", "/partner/v1/domains/{hostname}"),
        ("DELETE", "/partner/v1/sites/{id}"),
        ("DELETE", "/partner/v1/sites/{id}/domains/{hostname}"),
    }
    app = make_application()
    for method, path in INTAKE_WEBHOOK_PATHS:
        code, _ = _wsgi_call(app, method, path, body={})
        assert code == 404, f"{method} {path} must not be public (got {code})"
    code, _ = _wsgi_call(app, "POST", "/partner/v1/sites", body={})
    assert code != 404
    assert code in (401, 403)


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_intake_holds_no_webhook_secret():
    """Intake holds public keys + counters + outbox. No webhook secret / HMAC.

    What would make this fail: HUB_WEBHOOK_SECRET / GITHUB_WEBHOOK / whsec_ on
    intake, or FakeIntake growing a webhook_secret slot.
    """
    from intake.fake import FakeIntake

    for py in (REPO / "intake").rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        for needle in BANNED_INTAKE_NEEDLES:
            assert needle not in src, f"{py.relative_to(REPO)} contains {needle}"
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in BANNED_INTAKE_NEEDLES
    fake = FakeIntake()
    names = set(vars(fake)) | {name for name in dir(fake) if not name.startswith("_")}
    for banned in ("webhook_secret", "webhook_secrets", "hmac", "hmac_secret", "github_secret"):
        assert banned not in names
    assert not hasattr(fake, "webhook_secret")


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_unknown_outbox_type_refuses(monkeypatch):
    """Unknown outbox types refuse with an AuditEvent and do not enqueue.

    What would make this fail: treating github-webhook as git-push because it
    carries git_url/sha, or dropping the item with no audit row.
    """
    from monitor.intake_poll import FakeIntakeClient

    queued = _patch_delay(monkeypatch)
    site = _git_site(slug="unknown-type")
    client = FakeIntakeClient(items=[{
        "id": "job-mystery",
        "type": "github-webhook",
        "git_url": GIT_URL,
        "ref": "main",
        "sha": NEW_SHA,
    }])
    _poll(client, monkeypatch)
    assert queued == []
    assert Deployment.objects.filter(manifest__site=site).count() == 1
    row = AuditEvent.objects.get(action="outbox-type-refused")
    assert "github-webhook" in str(row.detail.get("type") or row.detail)
    assert "job-mystery" in client.acked


@pytest.mark.req("PART-K1-ZERO-INBOUND-HUB")
def test_hub_still_has_no_webhook_or_partner_inbound(client):
    """Hub urlpatterns still 404 git-webhook, /api/partner, and /mcp.

    What would make this fail: a Django webhook view or Hub /api/partner/*.
    """
    blob = " ".join(_route_strings())
    for needle in ("api/partner", "/mcp", "partner/v1", "github", "gitea", "deploy-hook"):
        assert needle not in blob
    for path in HUB_INBOUND:
        response = client.get(path)
        assert response.status_code == 404, f"GET {path} → {response.status_code}"
        response = client.post(path)
        assert response.status_code == 404, f"POST {path} → {response.status_code}"


@pytest.mark.req("PART-M2-GIT-WEBHOOK")
def test_git_push_run_twice_zero_mutating_calls(monkeypatch):
    """The same planted sha enqueued twice does not create a second deploy.

    What would make this fail: treating every poll tick as a new head, or
    delaying run_deploy again after Manifest N+1 already holds the sha.
    """
    from deploys import poller as git_poller
    from monitor.intake_poll import FakeIntakeClient

    queued = _patch_delay(monkeypatch)
    enqueues = []
    real_enqueue = git_poller._enqueue

    def wrapped(site, sha, latest):
        enqueues.append(sha)
        return real_enqueue(site, sha, latest)

    monkeypatch.setattr(git_poller, "_enqueue", wrapped)
    site = _git_site(slug="git-push-twice")
    client = FakeIntakeClient()
    client.plant_git_push(GIT_URL, "main", NEW_SHA, job_id="git-a")
    _poll(client, monkeypatch)
    assert enqueues == [NEW_SHA]
    assert len(queued) == 1
    after = Deployment.objects.filter(manifest__site=site).count()
    assert after == 2

    client.plant_git_push(GIT_URL, "main", NEW_SHA, job_id="git-b")
    _poll(client, monkeypatch)
    assert enqueues == [NEW_SHA]
    assert queued == queued[:1]
    assert Deployment.objects.filter(manifest__site=site).count() == after
