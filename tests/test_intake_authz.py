"""ZT-11: production intake is HTTPS, authenticated, and body-capped."""
import pytest
from django.test import override_settings

from monitor.intake_poll import IntakeClientError, _item_authenticated, intake_client_for

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=False, INTAKE_URL="http://intake.example.test", INTAKE_SERVICE_TOKEN="tok")
def test_http_intake_is_refused_in_production():
    with pytest.raises(IntakeClientError, match="https"):
        intake_client_for()


@override_settings(DEBUG=False, INTAKE_URL="https://intake.example.test", INTAKE_SERVICE_TOKEN="")
def test_production_intake_requires_service_token():
    with pytest.raises(IntakeClientError, match="INTAKE_SERVICE_TOKEN"):
        intake_client_for()


def test_intake_wsgi_refuses_oversized_bodies():
    """INT-01: CONTENT_LENGTH above the cap must not be read into memory."""
    from intake.app import make_application

    class Boom:
        def read(self, n=-1):
            raise AssertionError(f"intake read {n} bytes of an oversized body")

    captured = []

    def start_response(status, _headers):
        captured.append(status)

    app = make_application()
    app(
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/partner/v1/sites",
            "CONTENT_LENGTH": "2000000",
            "wsgi.input": Boom(),
        },
        start_response,
    )
    assert captured and captured[0].startswith("413")


@override_settings(DEBUG=False, INTAKE_SERVICE_TOKEN="secret")
def test_unauthenticated_git_push_item_is_refused():
    assert _item_authenticated({"id": "g1", "type": "git-push"}) is False
    import hashlib
    import hmac

    job = {
        "id": "g1",
        "type": "git-push",
        "git_url": "https://github.com/o/r.git",
        "ref": "main",
    }
    id_only = hmac.new(b"secret", b"g1", hashlib.sha256).hexdigest()
    assert _item_authenticated({**job, "hub_sig": id_only}) is False
    payload = "g1\ngit-push\nhttps://github.com/o/r.git\nmain"
    sig = hmac.new(b"secret", payload.encode(), hashlib.sha256).hexdigest()
    assert _item_authenticated({**job, "hub_sig": sig}) is True
    swapped = {**job, "git_url": "https://evil.example/r.git", "hub_sig": sig}
    assert _item_authenticated(swapped) is False
