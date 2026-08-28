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


@override_settings(DEBUG=False, INTAKE_SERVICE_TOKEN="secret")
def test_unauthenticated_git_push_item_is_refused():
    assert _item_authenticated({"id": "g1", "type": "git-push"}) is False
    import hashlib
    import hmac

    sig = hmac.new(b"secret", b"g1", hashlib.sha256).hexdigest()
    assert _item_authenticated({"id": "g1", "type": "git-push", "hub_sig": sig}) is True
