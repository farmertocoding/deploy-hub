"""ZT-07: workers reauthorize claimed workspace; replayed envelopes fail."""
from pathlib import Path

import pytest
import yaml

from core.models import Project, Workspace
from core.task_envelope import EnvelopeError, reauthorize, wrap

pytestmark = pytest.mark.django_db
REPO = Path(__file__).resolve().parent.parent


def test_replayed_or_tampered_envelope_fails_and_audits():
    from core.models import AuditEvent

    workspace = Workspace.objects.create(name="Env", slug="env-ws")
    other = Workspace.objects.create(name="Other", slug="env-other")
    project = Project.objects.create(
        workspace=workspace, name="p", slug="p-env",
    )
    envelope = wrap(
        task="scan",
        workspace_id=workspace.pk,
        resource_type="project",
        resource_id=project.pk,
    )
    reauthorize(envelope, resource=project)
    with pytest.raises(EnvelopeError, match="replay"):
        reauthorize(envelope, resource=project)
    tampered = wrap(
        task="scan",
        workspace_id=other.pk,
        resource_type="project",
        resource_id=project.pk,
    )
    with pytest.raises(EnvelopeError, match="workspace"):
        reauthorize(tampered, resource=project)
    assert AuditEvent.objects.filter(action="task_envelope_rejected").exists()


def test_two_same_workspace_wraps_in_one_second_are_not_replay(monkeypatch):
    """Nonce must include resource_id (or a random value), not just task+workspace+second.

    What would make this fail: wrap() hashing sha256(task:workspace_id:unix_second)
    so drain_hud_outbox wrapping two same-workspace outboxes in one second makes
    reauthorize treat the second as replay and skip process_outbox.
    """
    monkeypatch.setattr("core.task_envelope.time.time", lambda: 1_700_000_000)
    workspace = Workspace.objects.create(name="Nonce", slug="nonce-ws")
    first = wrap(
        task="core.tasks.process_hud_outbox",
        workspace_id=workspace.pk,
        resource_type="HudCommandOutbox",
        resource_id=11,
    )
    second = wrap(
        task="core.tasks.process_hud_outbox",
        workspace_id=workspace.pk,
        resource_type="HudCommandOutbox",
        resource_id=12,
    )
    assert first["nonce"] != second["nonce"]
    reauthorize(first)
    reauthorize(second)


def test_drain_hud_outbox_two_rows_same_second_both_reauthorize(monkeypatch):
    """Beat drain of two pending HUD rows in one second must not skip the second.

    What would make this fail: envelope_for_outbox nonces colliding so
    process_hud_outbox returns reason=envelope for the later row.
    """
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory

    from core.hud.operations import create_operation
    from core.models import HudCommandOutbox, NetworkZone
    from core.tasks import drain_hud_outbox, process_hud_outbox

    monkeypatch.setattr("core.task_envelope.time.time", lambda: 1_700_000_001)
    user = get_user_model().objects.create_user(
        "env-drain", password="pw-1234567890", is_staff=True, is_superuser=True,
    )
    factory = RequestFactory()
    request = factory.post("/api/v1/hud/targets/commands/")
    request.user = user
    request.headers = {}
    request.query_params = {}
    NetworkZone.objects.get_or_create(name="env-drain-net", slug="env-drain-net")
    create_operation(
        request, "target.create", object_type="Target",
        idempotency_key="env-drain-a",
    )
    create_operation(
        request, "target.create", object_type="Target",
        idempotency_key="env-drain-b",
    )
    pending = list(
        HudCommandOutbox.objects.filter(state=HudCommandOutbox.State.PENDING)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    assert len(pending) >= 2
    captured = []

    def fake_delay(outbox_id, envelope=None, **kwargs):
        captured.append((outbox_id, envelope))
        return None

    monkeypatch.setattr("core.tasks.process_hud_outbox.delay", fake_delay)
    drain_hud_outbox(limit=10)
    assert len(captured) >= 2
    nonces = [item[1]["nonce"] for item in captured]
    assert len(set(nonces)) == len(nonces)
    results = [
        process_hud_outbox(outbox_id, envelope)
        for outbox_id, envelope in captured
    ]
    assert all(row.get("reason") != "envelope" for row in results)


def test_hud_outbox_worker_requires_signed_envelope(monkeypatch):
    """Unsigned delay(outbox_id) must not run side effects.

    What would make this fail: process_hud_outbox skipping reauth when
    envelope is None, or _nudge_worker/drain delaying only the id.
    """
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory

    from core.hud.operations import _nudge_worker, create_operation
    from core.models import HudCommandOutbox, NetworkZone
    from core.tasks import drain_hud_outbox, process_hud_outbox

    user = get_user_model().objects.create_user(
        "env-op", password="pw-1234567890", is_staff=True, is_superuser=True,
    )
    factory = RequestFactory()
    request = factory.post("/api/v1/hud/targets/commands/")
    request.user = user
    request.headers = {}
    request.query_params = {}
    NetworkZone.objects.get_or_create(name="env-net", slug="env-net")
    operation, _created = create_operation(
        request, "target.create", object_type="Target",
        idempotency_key="env-nudge",
    )
    outbox = HudCommandOutbox.objects.get(operation=operation)
    unsigned = process_hud_outbox(outbox.pk)
    assert unsigned["ok"] is False
    assert unsigned["reason"] == "envelope"
    outbox.refresh_from_db()
    assert outbox.state == HudCommandOutbox.State.PENDING

    captured = []

    def fake_delay(outbox_id, envelope=None, **kwargs):
        captured.append((outbox_id, envelope))
        return None

    monkeypatch.setattr("core.tasks.process_hud_outbox.delay", fake_delay)
    assert _nudge_worker(outbox.pk) is True
    assert captured and captured[0][0] == outbox.pk
    envelope = captured[0][1]
    assert isinstance(envelope, dict) and envelope.get("sig")
    result = process_hud_outbox(outbox.pk, envelope)
    assert result["ok"] is True

    outbox.state = HudCommandOutbox.State.PENDING
    outbox.available_at = outbox.available_at
    outbox.save(update_fields=["state"])
    captured.clear()
    drain_hud_outbox(limit=10)
    assert captured
    assert all(item[1] and item[1].get("sig") for item in captured)


def test_probe_compose_uses_separate_credentials_and_no_kek():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    web = compose["services"]["web"]["environment"]
    probes = compose["services"]["worker-probes"]["environment"]
    assert probes["POSTGRES_PASSWORD"] != web["POSTGRES_PASSWORD"]
    assert probes["REDIS_PASSWORD"] != web["REDIS_PASSWORD"]
    assert not (probes.get("HUB_VAULT_KEYFILE") or "")
    volumes = compose["services"]["worker-probes"].get("volumes") or []
    mounts = {item.split(":")[0] for item in volumes}
    assert "hub-vault" not in mounts
