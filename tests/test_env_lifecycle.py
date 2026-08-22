"""Env lifecycle: config-stale, apply same image, names not values (PIPE-D2 / §E4)."""
import ast
import inspect
import json
from pathlib import Path

import pytest
from pipeline_fakes import PipelineTransport, fixture_body, queued_deployment

from deploys.models import Deployment, DeploymentArtifact, DeploymentStep
from providers.fakes import FakeDnsProvider

pytestmark = pytest.mark.django_db

PLANTED = "ENV-LIFECYCLE-SECRET-MARKER-do-not-log"


@pytest.fixture
def auth_client(client, django_user_model):
    """Logged-in operator with a confirmed second factor (§6.10)."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


def _site(*, slug="envlife"):
    from core.models import Project, Site

    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    from dns_fixtures import default_dns_zone

    return Site.objects.create(project=project, name=slug,
                               dns_zone=default_dns_zone())


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_put_env_marks_config_stale():
    """Add, edit, and delete through put_env all set Site.config_stale.

    What would make this fail: writing the mapping without flipping the flag,
    or storing values on Site / Manifest.body instead of a site-owned vault bundle.
    """
    from deploys.env import put_env
    from vault.models import Secret

    site = _site()
    assert site.config_stale is False

    put_env(site, {"DATABASE_URL": PLANTED})
    site.refresh_from_db()
    assert site.config_stale is True
    assert Secret.objects.filter(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type="site",
        owner_id=str(site.pk),
    ).exists()
    assert PLANTED not in json.dumps(site.__dict__, default=str)

    site.config_stale = False
    site.save(update_fields=["config_stale"])
    put_env(site, {"DATABASE_URL": "edited-" + PLANTED})
    site.refresh_from_db()
    assert site.config_stale is True

    site.config_stale = False
    site.save(update_fields=["config_stale"])
    put_env(site, {})
    site.refresh_from_db()
    assert site.config_stale is True


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_apply_skips_build_and_ship():
    """Apply enqueues Manifest N+1, skips build+ship, runs 4–9 on the existing tag.

    What would make this fail: docker build in mutating_calls, build/ship left
    pending/succeeded, a new git_sha (new image tag), or leaving config_stale set.
    """
    from deploys.env import apply_env, put_env

    site, original = queued_deployment("applyenv", body=fixture_body("applyenv"))
    old_body = dict(original.manifest.body)

    put_env(site, {"API_KEY": PLANTED})
    transport = PipelineTransport()
    dns = FakeDnsProvider()
    deployment = apply_env(site, transport=transport, dns=dns)

    assert deployment.pk != original.pk
    assert deployment.manifest.version == original.manifest.version + 1
    assert deployment.manifest.body.get("git_sha") == old_body.get("git_sha")

    by_name = {step.name: step.status for step in deployment.steps.order_by("seq")}
    assert by_name[DeploymentStep.Name.BUILD] == DeploymentStep.Status.SKIPPED
    assert by_name[DeploymentStep.Name.SHIP] == DeploymentStep.Status.SKIPPED
    for name in (
        DeploymentStep.Name.MIGRATE,
        DeploymentStep.Name.START_GREEN,
        DeploymentStep.Name.HEALTH_CHECK,
        DeploymentStep.Name.DNS,
        DeploymentStep.Name.ROUTE_TLS,
        DeploymentStep.Name.SMOKE_TEST,
        DeploymentStep.Name.CUTOVER,
    ):
        assert by_name[name] == DeploymentStep.Status.SUCCEEDED, name

    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED
    site.refresh_from_db()
    assert site.config_stale is False

    assert not any(
        kind == "run" and list(argv[:2]) == ["docker", "build"]
        for kind, argv in transport.mutating_calls()
    )


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_get_lists_names_not_values(auth_client):
    """GET /api/v1/sites/<id>/env/ lists names; planted values are absent from JSON.

    What would make this fail: echoing env values on GET, or omitting the names
    that put_env wrote.
    """
    from deploys.env import list_env_names, put_env

    site = _site(slug="envget")
    put_env(site, {"DATABASE_URL": PLANTED, "API_KEY": "also-" + PLANTED})

    assert list_env_names(site) == ["API_KEY", "DATABASE_URL"]

    response = auth_client.get(f"/api/v1/sites/{site.pk}/env/")
    assert response.status_code == 200
    payload = response.json()
    wire = json.dumps(payload)
    assert PLANTED not in wire
    names = payload.get("names") or payload.get("env_names")
    assert "DATABASE_URL" in names
    assert "API_KEY" in names

    written = auth_client.put(
        f"/api/v1/sites/{site.pk}/env/",
        data={"env": {"NEW_SECRET": PLANTED}},
        content_type="application/json",
    )
    assert written.status_code in (200, 201)
    assert PLANTED not in json.dumps(written.json())


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_values_not_in_task_kwargs_or_logs():
    """run_deploy stays ids-only; planted env never lands in artifacts or step logs.

    What would make this fail: extra Celery kwargs, snapshotting env values, or
    writing plaintext into DeploymentStep.log_text.
    """
    from deploys import tasks as deploy_tasks
    from deploys.env import apply_env, put_env
    from deploys.tasks import run_deploy

    source = ast.parse(Path(inspect.getfile(deploy_tasks)).read_text(encoding="utf-8"))
    for node in ast.walk(source):
        if isinstance(node, ast.FunctionDef) and node.name == "run_deploy":
            assert [a.arg for a in node.args.args] == ["deployment_id"]
            break
    else:
        pytest.fail("run_deploy is missing from deploys.tasks")
    assert list(inspect.signature(run_deploy).parameters) == ["deployment_id"]

    site, _original = queued_deployment("envlogs", body=fixture_body("envlogs"))
    put_env(site, {"DATABASE_URL": PLANTED})
    transport = PipelineTransport()
    deployment = apply_env(site, transport=transport, dns=FakeDnsProvider())

    for artifact in DeploymentArtifact.objects.filter(deployment=deployment):
        assert PLANTED not in artifact.content
    for step in deployment.steps.all():
        assert PLANTED not in step.log_text
    assert PLANTED not in json.dumps(deployment.manifest.body)


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_execute_clears_config_stale_after_delay(monkeypatch):
    """delay must not be the writer of config_stale; execute success is.

    What would make this fail: clearing only inside apply_env after a
    transport-injected execute, or leaving the flag set when the worker finishes.
    """
    from deploys.env import apply_env, put_env
    from deploys.pipeline import execute
    from deploys.tasks import run_deploy

    site, _original = queued_deployment("envdelay", body=fixture_body("envdelay"))
    put_env(site, {"API_KEY": PLANTED})
    site.refresh_from_db()
    assert site.config_stale is True

    queued = []
    monkeypatch.setattr(run_deploy, "delay", lambda pk: queued.append(pk))
    apply_env(site)
    site.refresh_from_db()
    assert site.config_stale is True
    assert queued

    execute(queued[0], transport=PipelineTransport(), dns=FakeDnsProvider())
    site.refresh_from_db()
    assert site.config_stale is False


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_apply_pins_last_succeeded_image_tag():
    """Apply docker-runs the last succeeded tag, not image_tag() of Manifest N+1.

    Wizard bodies carry env_bundle_ref; a new vault pk must not invent a tag
    that was never built. What would make this fail: hashing the new body, or
    omitting env fields from image_tag() so historical tags no longer match.
    """
    from deploys.env import apply_env, put_env
    from deploys.steps import image_tag
    from vault import service as vault_service
    from vault.models import Secret

    bundle = vault_service.put(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type="manifest",
        owner_id="pin-v1",
        plaintext=b'{"DATABASE_URL":"old"}',
    )
    body = fixture_body("envpin", extra={
        "env_bundle_ref": bundle.pk,
        "env_names": ["DATABASE_URL"],
    })
    site, original = queued_deployment("envpin", body=body)
    original.status = Deployment.Status.SUCCEEDED
    original.save(update_fields=["status"])
    prev_tag = image_tag(body["git_sha"], original.manifest.body)

    put_env(site, {"DATABASE_URL": PLANTED})
    transport = PipelineTransport()
    deployment = apply_env(site, transport=transport, dns=FakeDnsProvider())

    new_body = deployment.manifest.body
    computed = image_tag(new_body.get("git_sha"), new_body)
    assert computed != prev_tag
    runs = [
        argv for kind, argv in transport.mutating_calls()
        if kind == "run" and argv[:2] == ["docker", "run"]
    ]
    assert runs
    assert any(prev_tag in argv for argv in runs)
    assert all(computed not in argv for argv in runs)


def _docker_run_tags(transport):
    return [
        argv[-1]
        for kind, argv in transport.mutating_calls()
        if kind == "run" and argv[:2] == ["docker", "run"]
    ]


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_second_apply_reuses_original_built_tag():
    """Two sequential applies reuse the tag the first real build produced.

    What would make this fail: pinning image_tag() of the last apply Manifest
    (new env_bundle_ref) instead of the on-disk tag the succeeded row ran.
    """
    from deploys.env import apply_env, put_env
    from deploys.pipeline import execute
    from deploys.steps import image_tag

    site, original = queued_deployment("env2apply", body=fixture_body("env2apply"))
    transport = PipelineTransport()
    dns = FakeDnsProvider()
    execute(original.pk, transport=transport, dns=dns)
    original.refresh_from_db()
    assert original.status == Deployment.Status.SUCCEEDED
    built_tag = image_tag(
        original.manifest.body.get("git_sha"),
        original.manifest.body,
    )
    assert built_tag in _docker_run_tags(transport)

    put_env(site, {"API_KEY": "first-" + PLANTED})
    transport.calls.clear()
    first = apply_env(site, transport=transport, dns=dns)
    first_computed = image_tag(first.manifest.body.get("git_sha"), first.manifest.body)
    assert first_computed != built_tag
    assert _docker_run_tags(transport) == [built_tag]

    put_env(site, {"API_KEY": "second-" + PLANTED})
    transport.calls.clear()
    second = apply_env(site, transport=transport, dns=dns)
    second_computed = image_tag(
        second.manifest.body.get("git_sha"),
        second.manifest.body,
    )
    assert second_computed != built_tag
    assert second_computed != first_computed
    assert _docker_run_tags(transport) == [built_tag]
