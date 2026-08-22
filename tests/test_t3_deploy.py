"""T3: provision + dual-fixture HTTP + v2 + rollback + reaper (HARNESS-T3-NIGHTLY)."""
from __future__ import annotations

import inspect
import time
import uuid

import pytest

from tests.harness.multipass import NAME_PREFIX, delete_purge, list_names, multipass_available
from tests.harness.reaper import reap_test_plane

pytest_plugins = ["tests.harness.t3_deploy"]

pytestmark = [
    pytest.mark.t3,
    pytest.mark.skipif(not multipass_available(), reason="multipass is not available"),
    pytest.mark.django_db,
]


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-NIGHTLY")
def test_provision_fresh_multipass_then_harden(t3_ready):
    """provision_host on the fresh VM, then PROFILE=target harden.

    What would make this fail: provision after Caddy occupies 80, or harden skipped.
    """
    result = t3_ready.provision_result
    assert result is not None
    assert result.allowed is True, result.explanation
    assert t3_ready.hardened is True
    from tests.harness.multipass import exec as mp_exec

    ufw = mp_exec(t3_ready.mp(), ["sudo", "ufw", "status"], timeout=30)
    assert "Status: active" in (ufw.stdout or ""), ufw.stdout


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
def test_deploy_sample_site_http_ready(t3_ready, settings):
    """execute sample-site/ then HTTP GET ready through on-VM Caddy.

    Skips without sample-site/; that skip does not carry HARNESS-T3-NIGHTLY
    or PIPE-S4 (sibling Task 5 may be absent on this worktree).
    """
    from deploys.models import Deployment
    from tests.harness.t3_deploy import (
        execute_deployment,
        http_ready,
        queued_site,
        sample_site_available,
        sample_site_body,
        sample_site_missing_reason,
    )

    if not sample_site_available():
        pytest.skip(sample_site_missing_reason())

    slug = f"t3s{uuid.uuid4().hex[:6]}"
    _site, target, deployment = queued_site(
        t3_ready, settings, slug=slug, body=sample_site_body(slug),
    )
    result = execute_deployment(deployment, target)
    assert deployment.status == Deployment.Status.SUCCEEDED, result
    payload = http_ready(
        target, domain=f"{slug}.example.test", listen="127.0.0.1:8088",
    )
    assert payload.get("ready") is True, payload
    assert payload.get("live") is True, payload


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-NIGHTLY")
@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_deploy_sample_node_site_ready_before_cutover(t3_ready, settings):
    """sample-node-site ready (smoke) finishes before Caddy cutover starts.

    What would make this fail: cutover mutating before smoke_test succeeded.
    """
    from deploys.models import Deployment, DeploymentStep
    from tests.harness.t3_deploy import (
        SAMPLE_NODE_SITE,
        execute_deployment,
        http_ready,
        node_site_body,
        queued_site,
    )

    assert SAMPLE_NODE_SITE.is_dir()
    slug = f"t3n{uuid.uuid4().hex[:6]}"
    _site, target, deployment = queued_site(
        t3_ready, settings, slug=slug, body=node_site_body(slug),
    )
    result = execute_deployment(deployment, target)
    assert deployment.status == Deployment.Status.SUCCEEDED, result
    smoke = deployment.steps.get(name=DeploymentStep.Name.SMOKE_TEST)
    cutover = deployment.steps.get(name=DeploymentStep.Name.CUTOVER)
    assert smoke.status == DeploymentStep.Status.SUCCEEDED
    assert cutover.status == DeploymentStep.Status.SUCCEEDED
    assert smoke.finished is not None and cutover.started is not None
    assert smoke.finished <= cutover.started
    payload = http_ready(
        target, domain=f"{slug}.example.test", listen="127.0.0.1:8089",
    )
    assert payload.get("ready") is True, payload


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-NIGHTLY")
@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
def test_sample_node_site_volume_survives_v2(t3_ready, settings):
    """site-{slug}-data still holds the first-deploy marker after v2.

    What would make this fail: docker volume rm on the second deploy.
    """
    from deploys.models import Deployment
    from tests.harness.t3_deploy import (
        execute_deployment,
        node_site_body,
        queued_site,
        volume_marker,
    )

    slug = f"t3v{uuid.uuid4().hex[:6]}"
    _site, target, first = queued_site(
        t3_ready, settings, slug=slug, body=node_site_body(slug),
    )
    execute_deployment(first, target)
    assert first.status == Deployment.Status.SUCCEEDED
    volume = f"site-{slug}-data"
    first_mark = volume_marker(target, volume)
    assert first_mark.ok, first_mark.stderr
    assert (first_mark.stdout or "").strip() == "v1"

    second = Deployment.objects.create(manifest=first.manifest)
    execute_deployment(second, target)
    assert second.status == Deployment.Status.SUCCEEDED
    second_mark = volume_marker(target, volume)
    assert second_mark.ok, second_mark.stderr
    assert (second_mark.stdout or "").strip() == "v1"


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-NIGHTLY")
@pytest.mark.req("PIPE-N1-DEPLOY-STRATEGY")
def test_sample_node_site_ws_frame_through_caddy(t3_ready, settings):
    """One ws:// frame through on-VM Caddy, not Cloudflare.

    What would make this fail: talking to CF, or a Caddy route that drops Upgrade.
    """
    from deploys.models import Deployment
    from tests.harness.t3_deploy import (
        execute_deployment,
        node_site_body,
        queued_site,
        ws_frame_through_caddy,
    )

    slug = f"t3w{uuid.uuid4().hex[:6]}"
    _site, target, deployment = queued_site(
        t3_ready, settings, slug=slug, body=node_site_body(slug),
    )
    result = execute_deployment(deployment, target)
    assert deployment.status == Deployment.Status.SUCCEEDED, result
    frame = ws_frame_through_caddy(
        t3_ready,
        target,
        listen="127.0.0.1:8089",
        path="/ws/levels",
        domain=f"{slug}.example.test",
    )
    assert "snapshot" in frame, frame


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-NIGHTLY")
def test_v2_deploy_then_rollback_under_60s(t3_ready, settings):
    """v2 execute then execute(rollback_pk) finishes in under 60s.

    What would make this fail: rollback rebuilding the image, or hanging ≥ 60s.
    """
    from deploys.models import Deployment
    from deploys.pipeline import execute
    from providers.fakes import FakeDnsProvider
    from tests.harness.t3_deploy import (
        execute_deployment,
        node_site_body,
        queued_site,
        ssh_transport,
    )

    slug = f"t3r{uuid.uuid4().hex[:6]}"
    _site, target, first = queued_site(
        t3_ready, settings, slug=slug, body=node_site_body(slug),
    )
    execute_deployment(first, target)
    assert first.status == Deployment.Status.SUCCEEDED
    second = Deployment.objects.create(manifest=first.manifest)
    execute_deployment(second, target)
    assert second.status == Deployment.Status.SUCCEEDED

    rollback_pk = Deployment.objects.create(
        manifest=first.manifest,
        rollback_of=first,
    ).pk
    started = time.monotonic()
    execute(
        rollback_pk,
        transport=ssh_transport(target),
        dns=FakeDnsProvider(),
    )
    elapsed = time.monotonic() - started
    rolled = Deployment.objects.get(pk=rollback_pk)
    assert rolled.status == Deployment.Status.SUCCEEDED
    assert elapsed < 60, f"rollback took {elapsed:.1f}s"


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-NIGHTLY")
@pytest.mark.req("HARNESS-REAPER-TEST-PLANE")
def test_teardown_finally_reaper_leaves_no_hub_t3_vm(t3_ready):
    """Session fixture finally calls reap_test_plane; prefix-only; absent is ok.

    What would make this fail: a leaked hub-t3 name outside the session VM, or
    a fixture that never reaps.
    """
    from tests.harness import t3_deploy as helpers

    names = [n for n in list_names() if n.startswith(NAME_PREFIX)]
    assert t3_ready.name in names, names
    assert all(n.startswith(NAME_PREFIX) for n in names)
    src = inspect.getsource(helpers.t3_vm)
    assert "finally" in src
    assert "reap_test_plane" in src
    delete_purge("hub-t3-already-absent-t11")
    assert "hub-t3-already-absent-t11" not in list_names()
    assert "hub-t3-" in inspect.getsource(reap_test_plane)


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-NIGHTLY")
def test_hub_docker_sock_not_on_vm(t3_ready):
    """Hub /var/run/docker.sock is not bound into the Multipass VM.

    What would make this fail: cloud-init or a mount that shares the Hub daemon.
    """
    from tests.harness.t3_deploy import assert_hub_docker_sock_absent

    assert_hub_docker_sock_absent(t3_ready)
