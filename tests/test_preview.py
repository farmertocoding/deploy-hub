"""Phase 7.3: private-only preview Site + T2 HTTP (PREVIEW-PRIVATE-ONLY / PREVIEW-T2-HTTP).

create_preview never auto-deploys. Tests inject visibility on the view
callee the way restore wraps restore_to_clean. Do not mark P7-PREVIEW-DEMO.
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib
import uuid

import pytest
from django.contrib.auth.models import User
from django.urls import resolve
from test_aws_enroll import _login, _make_cred
from test_git_poller import TRIGGER_PATHS, WEBHOOK_NEEDLES, _route_strings

from tests.test_webauthn_t1 import T1_HTTP

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
PREVIEW_URL = "/api/v1/sites/{site_id}/preview/"
GIT_URL = "https://example.test/app.git"
FORBIDDEN_TOKENS = (
    "HUB_WEBHOOK_SECRET",
    "HUB_TEST_",
    "github.com/api",
)


def _preview_user(client):
    """Unique username so combined NAMED HTTP proofs share one transaction."""
    username = f"joseph-{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username, password="a-long-dev-password")
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    _login(client, user)
    return user


def _parent(*, name="app", source_kind=None, git_url=GIT_URL):
    from core.models import NetworkZone, Project, Site, Target

    kind = source_kind or Project.Source.GIT
    project = Project.objects.create(
        name=name,
        slug=f"p-{name}",
        source_kind=kind,
        git_url=git_url,
    )
    zone = NetworkZone.objects.create(name=f"z-{name}", slug=f"z-{name}")
    target = Target.objects.create(zone=zone, host=f"{name}.lan")
    return Site.objects.create(
        project=project,
        name=name,
        exposure=Site.Exposure.MESH_ONLY,
        primary_target=target,
    )


def _inject_visibility(monkeypatch, visibility):
    """Wrap the view callee so HTTP can pass visibility= (restore wrap)."""
    from deploys import preview as preview_mod

    real = preview_mod.create_preview

    def wrapped(parent, ref, *, visibility=None):
        return real(parent, ref, visibility=visibility or injected)

    injected = visibility
    monkeypatch.setattr("deploys.preview_views.create_preview", wrapped)


def _post_preview(client, site, *, ref="feature/pr-12", confirm_name=None):
    body = {
        "ref": ref,
        "confirm_name": site.name if confirm_name is None else confirm_name,
    }
    return client.post(
        PREVIEW_URL.format(site_id=site.pk),
        data=json.dumps(body),
        content_type="application/json",
    )


def _preview_modules():
    return (
        REPO / "deploys" / "preview.py",
        REPO / "deploys" / "preview_views.py",
    )


def _assert_no_webhook_ast():
    for path in _preview_modules():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for token in FORBIDDEN_TOKENS:
            assert token not in source, f"{path.name} names {token}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lowered = node.value.lower()
                assert "webhook" not in lowered, f"{path.name} string {node.value!r}"
                assert "github.com/api" not in node.value
            if isinstance(node, ast.Attribute):
                name = node.attr.lower()
                assert "webhook" not in name, f"{path.name} attr {node.attr}"


# ── C1 create_preview ─────────────────────────────────────────────────────────


@pytest.mark.req("PREVIEW-PRIVATE-ONLY")
def test_private_creates_mesh_only_sibling():
    """visibility=private creates one mesh-only sibling; preview_of + preview_ref.

    What would make this fail: a public exposure, missing preview_of, calling
    run_deploy, or naming the sibling without the preview- prefix.
    """
    from core.models import Site
    from deploys.models import Deployment
    from deploys.preview import create_preview

    parent = _parent(name="shop")
    before = Deployment.objects.count()
    sibling = create_preview(parent, "feature/pr-12", visibility="private")
    sibling.refresh_from_db()
    assert sibling.pk != parent.pk
    assert sibling.project_id == parent.project_id
    assert sibling.name == "preview-shop-feature-pr-12"
    assert sibling.exposure == Site.Exposure.MESH_ONLY
    assert sibling.preview_of_id == parent.pk
    assert sibling.preview_ref == "feature/pr-12"
    assert sibling.primary_target_id == parent.primary_target_id
    assert sibling.dns_zone_id is None
    assert parent.previews.get().pk == sibling.pk
    assert Deployment.objects.count() == before


@pytest.mark.req("PREVIEW-PRIVATE-ONLY")
def test_public_refuses():
    """visibility=public must not create a Site.

    What would make this fail: treating public as allowed so a PR from an
    untrusted repo becomes a preview row.
    """
    from core.models import Site
    from deploys.preview import PreviewError, create_preview

    parent = _parent(name="pub")
    before = Site.objects.count()
    with pytest.raises(PreviewError) as exc:
        create_preview(parent, "feature/pr-12", visibility="public")
    assert exc.value.reason == "public repo refused"
    assert Site.objects.count() == before


@pytest.mark.req("PREVIEW-PRIVATE-ONLY")
def test_missing_visibility_refuses():
    """visibility is None (the default) refuses.

    What would make this fail: defaulting missing visibility to private.
    """
    from core.models import Site
    from deploys.preview import PreviewError, create_preview

    parent = _parent(name="miss")
    before = Site.objects.count()
    with pytest.raises(PreviewError) as exc:
        create_preview(parent, "feature/pr-12")
    assert exc.value.reason == "visibility refused"
    assert Site.objects.count() == before


@pytest.mark.req("PREVIEW-PRIVATE-ONLY")
def test_non_git_parent_refuses():
    """local_path / empty git_url is not a git project.

    What would make this fail: creating a preview from a path-only Project.
    """
    from core.models import Project, Site
    from deploys.preview import PreviewError, create_preview

    parent = _parent(
        name="local",
        source_kind=Project.Source.LOCAL_PATH,
        git_url="",
    )
    before = Site.objects.count()
    with pytest.raises(PreviewError) as exc:
        create_preview(parent, "feature/pr-12", visibility="private")
    assert exc.value.reason == "not a git project"
    assert Site.objects.count() == before


@pytest.mark.req("PREVIEW-PRIVATE-ONLY")
def test_create_preview_does_not_call_run_deploy(monkeypatch):
    """create_preview must not import or call run_deploy / poll_git / overflow.

    What would make this fail: enqueueing a deploy, polling git, or an overflow
    side effect when the operator only asked for a sibling Site row.
    """
    from deploys.preview import create_preview
    from deploys.tasks import run_deploy

    called = []
    monkeypatch.setattr(run_deploy, "delay", lambda pk: called.append(pk))
    monkeypatch.setattr(run_deploy, "apply_async", lambda *a, **k: called.append(a))

    parent = _parent(name="nodply")
    create_preview(parent, "feature/pr-12", visibility="private")
    assert called == []

    source = inspect.getsource(create_preview)
    for needle in ("run_deploy", "poll_git", "overflow"):
        assert needle not in source, needle
    _assert_no_webhook_ast()


# ── C3 T2 HTTP ────────────────────────────────────────────────────────────────


@pytest.mark.req("PREVIEW-T2-HTTP")
def test_preview_http_private_201(client, monkeypatch):
    """T2 POST site.preview_create: type-the-parent-name; 201 site_id parent_id ref.

    What would make this fail: RequireRecentTouch, a T1 row, or a 201 that
    omits the new site id.
    """
    from core.actions import ACTION_TIERS
    from core.models import Site
    from core.permissions import RequireRecentTouch
    from deploys.preview_views import PreviewCreateSerializer, SitePreviewCreateView

    row = next(r for r in ACTION_TIERS if r["id"] == "site.preview_create")
    assert row == {"id": "site.preview_create", "tier": "T2", "label": "Create preview"}
    assert "site.preview_create" not in T1_HTTP
    assert RequireRecentTouch not in SitePreviewCreateView.permission_classes

    match = resolve(PREVIEW_URL.format(site_id=1))
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is SitePreviewCreateView
    assert set(PreviewCreateSerializer().get_fields()) == {"ref", "confirm_name"}
    view_src = inspect.getsource(SitePreviewCreateView)
    assert "RequireRecentTouch" not in view_src
    assert "request.data.get" not in view_src
    assert "visibility=\"private\"" not in view_src
    assert "visibility='private'" not in view_src
    from deploys.preview_views import create_preview as view_create_preview
    assert inspect.signature(view_create_preview).parameters["visibility"].default is None

    _preview_user(client)
    _inject_visibility(monkeypatch, "private")
    parent = _parent(name="httpok")
    response = _post_preview(client, parent, ref="feature/pr-12")
    assert response.status_code == 201, response.content
    body = response.json()
    sibling = Site.objects.get(preview_of=parent)
    assert body == {
        "ok": True,
        "site_id": sibling.pk,
        "parent_id": parent.pk,
        "ref": "feature/pr-12",
    }
    assert sibling.exposure == Site.Exposure.MESH_ONLY
    assert sibling.name == "preview-httpok-feature-pr-12"


@pytest.mark.req("PREVIEW-T2-HTTP")
def test_preview_http_public_4xx(client, monkeypatch):
    """Injected visibility=public → 4xx public repo refused; no sibling.

    What would make this fail: HTTP ignoring the inject and creating a Site.
    """
    from core.models import Site

    _preview_user(client)
    _inject_visibility(monkeypatch, "public")
    parent = _parent(name="httppub")
    before = Site.objects.count()
    response = _post_preview(client, parent)
    assert 400 <= response.status_code < 500, response.content
    assert response.json()["detail"] == "public repo refused"
    assert Site.objects.count() == before


@pytest.mark.req("PREVIEW-T2-HTTP")
def test_preview_http_missing_inject_4xx(client, monkeypatch):
    """View default visibility=None → 4xx visibility refused.

    What would make this fail: the view hard-coding visibility=private so a
    missing inject still creates a Site.
    """
    from core.models import Site
    from deploys.preview import create_preview

    monkeypatch.setattr(
        "deploys.preview_views.create_preview",
        create_preview,
    )
    _preview_user(client)
    parent = _parent(name="httpmiss")
    before = Site.objects.count()
    response = _post_preview(client, parent)
    assert 400 <= response.status_code < 500, response.content
    assert response.json()["detail"] == "visibility refused"
    assert Site.objects.count() == before


@pytest.mark.req("PREVIEW-T2-HTTP")
def test_preview_wrong_confirm_4xx(client, monkeypatch):
    """confirm_name != parent.name → 4xx; no sibling.

    What would make this fail: confirm_name ignored so any string creates.
    """
    from core.models import Site

    _preview_user(client)
    _inject_visibility(monkeypatch, "private")
    parent = _parent(name="httpwrong")
    before = Site.objects.count()
    response = _post_preview(client, parent, confirm_name="wrong-site")
    assert 400 <= response.status_code < 500, response.content
    assert Site.objects.count() == before


@pytest.mark.req("PREVIEW-T2-HTTP")
def test_no_webhook_route(client):
    """New preview modules add no webhook / github route or secret name.

    What would make this fail: a /webhook path, HUB_WEBHOOK_SECRET, or a
    GitHub HTTP client in preview.py / preview_views.py.
    """
    _assert_no_webhook_ast()
    offenders = [
        route for route in _route_strings()
        if any(needle in route for needle in WEBHOOK_NEEDLES)
        and "preview" in route
    ]
    assert offenders == []
    for path in TRIGGER_PATHS:
        response = client.get(path)
        assert response.status_code == 404, f"{path} returned {response.status_code}"
    urls = (REPO / "deploys" / "urls.py").read_text(encoding="utf-8")
    assert "webhook" not in urls.lower()
    assert "github" not in urls.lower()


def test_view_resolves_visibility_from_git_provider(client, monkeypatch):
    """A configured FakeGitVisibility private repo creates the sibling.

    What would make this fail: still calling create_preview without
    visibility, or taking visibility from the JSON body.
    """
    from core.models import Site
    from providers.fakes import FakeGitVisibility

    fake = FakeGitVisibility("private")
    monkeypatch.setattr("deploys.preview_views.git_visibility_for", lambda _p: fake)
    _preview_user(client)
    parent = _parent(name="resolved")
    response = _post_preview(client, parent, ref="feature/from-provider")
    assert response.status_code == 201, response.content
    sibling = Site.objects.get(preview_of=parent)
    assert sibling.exposure == Site.Exposure.MESH_ONLY
    assert fake.calls == [GIT_URL]


def test_preview_rejects_client_supplied_visibility(client, monkeypatch):
    """A body visibility field is 400 even when a provider would allow private."""
    from core.models import Site
    from providers.fakes import FakeGitVisibility

    monkeypatch.setattr(
        "deploys.preview_views.git_visibility_for",
        lambda _p: FakeGitVisibility("private"),
    )
    _preview_user(client)
    parent = _parent(name="nosupply")
    before = Site.objects.count()
    response = client.post(
        PREVIEW_URL.format(site_id=parent.pk),
        data=json.dumps({
            "ref": "main",
            "confirm_name": parent.name,
            "visibility": "private",
        }),
        content_type="application/json",
    )
    assert response.status_code == 400, response.content
    assert Site.objects.count() == before
