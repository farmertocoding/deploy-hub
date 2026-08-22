"""T1: Settings Cloudflare-connect (Task 12b) — paste a token, observe it
through the ONE pinned helper, vault it, then create the DnsAccount + DnsZone
rows. Inactive / Global-API-Key shape / multi-zone tokens are refused with
the reason and create nothing. The token never comes back in the response.
"""
import ast
import json
import pathlib

import pytest
from test_cloudflare_adapter import FakeCloudflare

TOKEN = "t1-connect-dummy-token-not-a-credential"  # nosec B105 — a test constant
ZONE_ID = "zid-connect"
ZONE_NAME = "connect.example"
CONNECT = "/api/v1/cloudflare/connect/"
VERIFY = ("GET", "/user/tokens/verify")
PROBE = ("GET", "/zones?per_page=50")

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _fresh_scope_cache():
    import providers.registry as registry

    registry.reset_scope_cache()
    yield
    registry.reset_scope_cache()


def _enrolled_client(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.login(username="joseph", password="a-long-dev-password")
    return user


def _http(monkeypatch, *, status="active", zones=None):
    import providers.cloudflare as cloudflare

    if zones is None:
        zones = [{"id": ZONE_ID, "name": ZONE_NAME}]
    http = FakeCloudflare({
        VERIFY: {"success": True, "result": {"id": "tok", "status": status}},
        PROBE: {"success": True, "result": zones},
    })
    monkeypatch.setattr(cloudflare, "urlopen", http)
    return http


def _connect(client, token=TOKEN):
    return client.post(CONNECT, {"token": token}, content_type="application/json")


def test_valid_single_zone_token_creates_account_and_zone_rows(client, monkeypatch):
    """An active token that reaches exactly one zone becomes the rows.

    What would make this fail: observing the token and then forgetting to
    persist the account/zone the Settings screen is supposed to show, or
    creating them before the probe so a refused token still leaves rows.
    """
    from core.models import DnsAccount, DnsZone

    _enrolled_client(client)
    _http(monkeypatch)

    response = _connect(client)
    assert response.status_code == 201, response.content
    body = response.json()
    assert DnsAccount.objects.count() == 1
    assert DnsZone.objects.count() == 1
    account = DnsAccount.objects.get()
    zone = DnsZone.objects.get()
    assert account.provider == "cloudflare"
    assert account.dns_token_ref
    assert zone.account_id == account.pk
    assert zone.name == ZONE_NAME
    assert zone.provider_zone_id == ZONE_ID
    assert zone.purpose == DnsZone.Purpose.PROD
    assert body["account"]["id"] == account.pk
    assert body["zone"]["name"] == ZONE_NAME
    assert body["zone"]["provider_zone_id"] == ZONE_ID
    assert body["zone"]["purpose"] == "prod"


def test_multi_zone_token_is_refused_with_the_reason(client, monkeypatch):
    """A token that reaches two zones is refused at this screen, with why.

    What would make this fail: connecting anyway and binding the first zone,
    or a bare 400 with no reason the Settings panel can show.
    """
    from core.models import DnsAccount, DnsZone
    from vault.models import Secret

    _enrolled_client(client)
    _http(monkeypatch, zones=[
        {"id": ZONE_ID, "name": ZONE_NAME},
        {"id": "zid-extra", "name": "extra.example"},
    ])

    response = _connect(client)
    assert response.status_code == 400
    errors = response.json()["errors"]
    reason = errors["token"][0]["message"]
    assert "2" in reason
    assert DnsAccount.objects.count() == 0
    assert DnsZone.objects.count() == 0
    assert Secret.objects.filter(owner_type="dns_account").count() == 0


def test_inactive_or_global_key_is_refused(client, monkeypatch):
    """Inactive tokens and Global-API-Key shapes create nothing.

    What would make this fail: treating verify-not-active as a network
    hiccup and retrying into a row, or putting an X-Auth-Key document on
    the wire instead of refusing by shape.
    """
    from core.models import DnsAccount, DnsZone
    from vault.models import Secret

    _enrolled_client(client)

    http = _http(monkeypatch, status="disabled")
    inactive = _connect(client)
    assert inactive.status_code == 400
    assert "token" in inactive.json()["errors"]
    assert "active" in inactive.json()["errors"]["token"][0]["message"]
    assert DnsAccount.objects.count() == 0
    assert [req[:2] for req in http.requests] == [VERIFY]  # probe skipped

    shaped = _connect(client, token=json.dumps({
        "api_key": "not-a-bearer", "email": "ops@example.com",
    }))
    assert shaped.status_code == 400
    reason = shaped.json()["errors"]["token"][0]["message"].lower()
    assert "global api key" in reason or "structured" in reason
    assert DnsAccount.objects.count() == 0
    assert DnsZone.objects.count() == 0
    assert Secret.objects.filter(owner_type="dns_account").count() == 0
    assert http.methods() == ["GET"]  # still just the inactive verify


def test_token_is_vaulted_and_never_returned_by_the_api(client, monkeypatch):
    """The pasted token is stored through vault.put and never echoed.

    What would make this fail: putting the token on DnsAccount, in the
    response body, or in a log-shaped field the Settings panel could
    render. The only read path is vault.get.
    """
    from core.models import DnsAccount
    from vault import service as vault_service
    from vault.models import Secret

    _enrolled_client(client)
    _http(monkeypatch)

    response = _connect(client)
    assert response.status_code == 201
    raw = response.content.decode()
    assert TOKEN not in raw
    body = response.json()
    assert "token" not in body
    assert "token" not in body.get("account", {})
    dumped = json.dumps(body)
    assert TOKEN not in dumped

    account = DnsAccount.objects.get()
    secret = Secret.objects.get(
        kind=Secret.Kind.API_TOKEN,
        owner_type="dns_account",
        owner_id=account.dns_token_ref,
    )
    assert vault_service.get(secret, reason="connect-test") == TOKEN.encode()


def test_connect_uses_the_same_verification_helper_as_construction(monkeypatch, client):
    """Connect and dns_provider_for both ride cloudflare.observe_token.

    What would make this fail: the Settings view re-spelling verify+probe
    (or calling urlopen itself) so a token the wall would refuse gets
    connected, or vice versa. Same sharing-spy pattern as
    tests/test_cf_token_audit.py.
    """
    import providers.cloudflare as cloudflare
    from core.models import DnsZone
    from providers.registry import dns_provider_for

    calls = []
    real = cloudflare.observe_token

    def spy(token, **kwargs):
        calls.append(token.decode() if isinstance(token, bytes) else token)
        return real(token, **kwargs)

    monkeypatch.setattr(cloudflare, "observe_token", spy)
    _http(monkeypatch)
    _enrolled_client(client)

    response = _connect(client)
    assert response.status_code == 201
    assert calls == [TOKEN], "connect must route through observe_token"

    dns_provider_for(DnsZone.objects.get())
    assert calls == [TOKEN, TOKEN], "construction must reuse the same helper"

    tree = ast.parse((REPO / "core" / "zone_views.py").read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
        in {"api_request", "urlopen"}
    ]
    assert offenders == [], f"zone_views spells its own Cloudflare call: {offenders}"


def test_connect_requires_session(client, monkeypatch):
    """The token is a credential — session-gated like findings (§6.10)."""
    _http(monkeypatch)
    assert client.post(
        CONNECT, {"token": TOKEN}, content_type="application/json",
    ).status_code == 403


def test_failed_row_create_revokes_the_vaulted_secret(client, monkeypatch):
    """A vaulted token whose rows cannot be created must not stay in the vault.

    What would make this fail: put() succeeding and then a unique-zone
    clash leaving an orphan Secret the operator cannot see or rotate.
    """
    from core.models import DnsAccount, DnsZone
    from vault.models import Secret

    other = DnsAccount.objects.create(provider="cloudflare", label="existing")
    DnsZone.objects.create(
        account=other, name=ZONE_NAME, provider_zone_id="zid-existing",
    )
    _enrolled_client(client)
    _http(monkeypatch)

    response = _connect(client)
    assert response.status_code == 400
    assert "already exists" in response.json()["errors"]["token"][0]["message"]
    assert DnsAccount.objects.count() == 1
    assert DnsZone.objects.count() == 1
    assert Secret.objects.filter(owner_type="dns_account").count() == 0
