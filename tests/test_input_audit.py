"""VAL-45-REJECTED-INPUT-AUDITED — rejected input is recorded, values never are."""
import pytest
from django.test import override_settings
from django.urls import reverse

from core.models import AuditEvent

pytestmark = pytest.mark.django_db

SECRET_VALUE = "hunter2-SUPER-SECRET-PASSWORD-MARKER"


def _rejected_events():
    return AuditEvent.objects.filter(action="input_rejected")


@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
def test_rejected_input_is_audited(client):
    """Missing required field → 400 → one audit row naming the field."""
    response = client.post(
        reverse("login"), data={"username": "alice"}, content_type="application/json"
    )
    assert response.status_code == 400
    event = _rejected_events().first()
    assert event is not None
    assert "password" in event.detail["fields"]
    assert event.detail["method"] == "POST"
    assert event.severity == AuditEvent.Severity.WARNING


@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
def test_rejected_values_are_never_recorded(client):
    """The row carries field paths and error codes. Never values — a rejected env
    answer is a secret that failed validation."""
    client.post(
        reverse("login"),
        data={"username": "", "password": SECRET_VALUE},
        content_type="application/json",
    )
    event = _rejected_events().first()
    assert event is not None
    assert SECRET_VALUE not in str(event.detail)
    assert SECRET_VALUE not in str(event.__dict__)


@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
def test_codes_are_recorded_for_triage(client):
    client.post(
        reverse("login"), data={"username": "alice"}, content_type="application/json"
    )
    event = _rejected_events().first()
    assert "required" in event.detail["codes"]


@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
def test_successful_request_is_not_audited_as_rejection(client, django_user_model):
    django_user_model.objects.create_user(username="bob", password="correct-horse-1234")
    client.post(
        reverse("login"),
        data={"username": "bob", "password": "correct-horse-1234"},
        content_type="application/json",
    )
    assert not _rejected_events().exists()


@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
def test_source_ip_recorded_from_remote_addr(client):
    client.post(
        reverse("login"),
        data={"username": "alice"},
        content_type="application/json",
        REMOTE_ADDR="203.0.113.9",
    )
    assert _rejected_events().first().source_ip == "203.0.113.9"


@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
@override_settings(HUB_TRUSTED_PROXY_HOPS=1)
def test_forwarded_for_is_not_forgeable(client):
    """X-Forwarded-For is caller-controlled. With one real proxy in front, the client
    can prepend anything it likes; only the rightmost entry was written by our own
    proxy. Trusting the leftmost would let an attacker forge the source IP in the
    audit trail meant to identify them."""
    client.post(
        reverse("login"),
        data={"username": "alice"},
        content_type="application/json",
        HTTP_X_FORWARDED_FOR="1.2.3.4, 198.51.100.7",
        REMOTE_ADDR="10.0.0.1",
    )
    assert _rejected_events().first().source_ip == "198.51.100.7"


@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
def test_forwarded_for_ignored_when_no_proxy_configured(client):
    """Zero configured hops (the default): the header is decoration and REMOTE_ADDR
    is the truth."""
    client.post(
        reverse("login"),
        data={"username": "alice"},
        content_type="application/json",
        HTTP_X_FORWARDED_FOR="1.2.3.4",
        REMOTE_ADDR="10.0.0.1",
    )
    assert _rejected_events().first().source_ip == "10.0.0.1"


@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
def test_nested_field_paths_are_flattened(rf):
    """Wizard answers arrive nested; a row saying 'answers' would be useless for
    triage. The path, not the value, is what makes the signal actionable."""
    from rest_framework.exceptions import ValidationError

    from core.exception_handlers import audited_exception_handler

    request = rf.post("/api/v1/sites/1/wizard/")
    request.user = None
    exc = ValidationError({"answers": {"DATABASE_URL": ["This field is required."]}})
    audited_exception_handler(exc, {"request": request, "view": None})
    assert _rejected_events().first().detail["fields"] == ["answers.DATABASE_URL"]
