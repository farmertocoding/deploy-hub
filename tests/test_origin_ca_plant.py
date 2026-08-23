"""Origin-CA file plant (TLS-B2-ORIGIN-CA-PLANT / I-plant / S1 / S5).

Hub-local path only. Vault shape matches origin_cert_issuer_for. Key bytes
never enter the request, response, Finding, or Settings-connect form.
"""
from pathlib import Path

import pytest
from django.test import override_settings
from test_cloudflare_adapter import FakeCloudflare

from core.models import DnsAccount, Finding, Project, Site
from deploys.seams import DeploySeamRefused, resolve_production_seams
from vault import service as vault_service
from vault.models import Secret

pytestmark = pytest.mark.django_db

KEY_BYTES = b"t1-plant-oca-key-bytes-not-a-credential"
TOKEN = "t1-connect-dummy-token-not-a-credential"  # nosec B105 — test constant
CONNECT = "/api/v1/cloudflare/connect/"
VERIFY = ("GET", "/user/tokens/verify")
PROBE = ("GET", "/zones?per_page=50")


@pytest.fixture
def auth_client(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


def _account(*, label="plant-acct"):
    return DnsAccount.objects.create(
        provider=DnsAccount.Provider.CLOUDFLARE, label=label,
    )


def _plant_url(account):
    return f"/api/v1/dns-accounts/{account.pk}/origin-ca-plant/"


def _allowlisted_file(tmp_path, monkeypatch, *, mode=0o600, name="oca.key",
                      data=KEY_BYTES):
    import core.zone_views as zone_views

    root = tmp_path / "origin-ca"
    root.mkdir(exist_ok=True)
    path = root / name
    path.write_bytes(data)
    path.chmod(mode)
    monkeypatch.setattr(zone_views, "ORIGIN_CA_PLANT_ROOTS", (Path(root),))
    return path


def _plant(client, account, path):
    return client.post(
        _plant_url(account), {"path": str(path)}, content_type="application/json",
    )


def _public_site(account):
    from core.models import DnsZone, NetworkZone, Target

    zone = DnsZone.objects.create(
        account=account, name="plant.example", provider_zone_id="zid-plant",
    )
    project = Project.objects.create(name="plant-site", slug="plant-site")
    net = NetworkZone.objects.create(name="plant-net", slug="plant-net")
    target = Target.objects.create(zone=net, host="plant-host.example.com")
    return Site.objects.create(
        project=project, name="plant-site", domain="app.plant.example",
        primary_target=target, dns_zone=zone, proxied=True,
    )


def _vault_dns_token(account):
    vault_service.put(
        kind=Secret.Kind.API_TOKEN,
        owner_type="dns_account",
        owner_id="dns-ref-plant",
        plaintext=b"t1-seam-dns-token-not-a-credential",
    )
    account.dns_token_ref = "dns-ref-plant"
    account.save(update_fields=["dns_token_ref"])


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_plant_from_allowlisted_0600_file_sets_origin_ca_key_ref(
        auth_client, tmp_path, monkeypatch):
    """A 0600 file under an Origin-CA subdir becomes origin_ca_key_ref.

    What would make this fail: storing the path instead of vaulting the
    bytes, or leaving origin_ca_key_ref blank after a successful plant.
    """
    account = _account()
    path = _allowlisted_file(tmp_path, monkeypatch)
    response = _plant(auth_client, account, path)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["planted"] is True
    account.refresh_from_db()
    assert account.origin_ca_key_ref
    secret = Secret.objects.get(
        kind=Secret.Kind.API_TOKEN,
        owner_type="dns_account",
        owner_id=account.origin_ca_key_ref,
    )
    assert vault_service.get(secret, reason="plant-test") == KEY_BYTES


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_plant_rejects_path_outside_origin_ca_subdir(auth_client, tmp_path):
    """A 0600 file that is not under an Origin-CA subdir is refused (S1).

    What would make this fail: planting from /tmp or /etc/deploy-hub/ wholesale.
    """
    account = _account()
    path = tmp_path / "outside.key"
    path.write_bytes(KEY_BYTES)
    path.chmod(0o600)
    response = _plant(auth_client, account, path)
    assert response.status_code == 400, response.content
    account.refresh_from_db()
    assert account.origin_ca_key_ref == ""
    assert not Secret.objects.filter(owner_type="dns_account").exists()


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_plant_rejects_0644_file(auth_client, tmp_path, monkeypatch):
    """0644 is world-readable — refuse even inside an allowlisted root (S5)."""
    account = _account()
    path = _allowlisted_file(tmp_path, monkeypatch, mode=0o644)
    response = _plant(auth_client, account, path)
    assert response.status_code == 400, response.content
    account.refresh_from_db()
    assert account.origin_ca_key_ref == ""


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_plant_rejects_symlink(auth_client, tmp_path, monkeypatch):
    """A symlink is refused even when its target is a 0600 allowlisted file (S5)."""
    account = _account()
    target = _allowlisted_file(tmp_path, monkeypatch, name="real.key")
    link = target.parent / "link.key"
    link.symlink_to(target)
    response = _plant(auth_client, account, link)
    assert response.status_code == 400, response.content
    account.refresh_from_db()
    assert account.origin_ca_key_ref == ""


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_plant_rejects_vault_keyfile_path(auth_client, tmp_path, monkeypatch):
    """VAULT_KEYFILE is never a plant source, even if it sits under a root (S5)."""
    account = _account()
    path = _allowlisted_file(tmp_path, monkeypatch)
    with override_settings(VAULT_KEYFILE=str(path)):
        response = _plant(auth_client, account, path)
    assert response.status_code == 400, response.content
    account.refresh_from_db()
    assert account.origin_ca_key_ref == ""


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_plant_request_and_response_contain_no_key_bytes(
        auth_client, tmp_path, monkeypatch):
    """Key bytes stay on disk → vault. They do not ride the HTTP envelope.

    What would make this fail: echoing file contents, accepting an
    origin_ca_key field, or filing a Finding that quotes the key.
    """
    account = _account()
    path = _allowlisted_file(tmp_path, monkeypatch)
    marker = KEY_BYTES.decode()

    stuffed = auth_client.post(
        _plant_url(account),
        {"path": str(path), "origin_ca_key": marker},
        content_type="application/json",
    )
    assert stuffed.status_code == 400
    assert marker not in stuffed.content.decode()
    account.refresh_from_db()
    assert account.origin_ca_key_ref == ""

    response = _plant(auth_client, account, path)
    assert response.status_code == 200, response.content
    raw = response.content.decode()
    assert marker not in raw
    assert "origin_ca_key" not in response.json()
    assert not any(
        marker in ((row.body or "") + (row.title or "") + (row.fix_action or ""))
        for row in Finding.objects.all()
    )


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_plant_uses_api_token_dns_account_vault_shape(
        auth_client, tmp_path, monkeypatch):
    """Plant writes the same vault row origin_cert_issuer_for already loads.

    What would make this fail: a new Secret.Kind, owner_type=site, or minting
    a second ref when origin_ca_key_ref is already set.
    """
    account = _account()
    account.origin_ca_key_ref = "reuse-me-please"
    account.save(update_fields=["origin_ca_key_ref"])
    path = _allowlisted_file(tmp_path, monkeypatch)
    response = _plant(auth_client, account, path)
    assert response.status_code == 200, response.content
    account.refresh_from_db()
    assert account.origin_ca_key_ref == "reuse-me-please"
    secret = Secret.objects.get(
        kind=Secret.Kind.API_TOKEN,
        owner_type="dns_account",
        owner_id="reuse-me-please",
    )
    assert vault_service.get(secret, reason="plant-shape") == KEY_BYTES


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_connect_endpoint_still_does_not_accept_an_origin_ca_key(
        auth_client, monkeypatch):
    """Settings-connect stays DNS-token only — extra key fields are not vaulted."""
    import providers.cloudflare as cloudflare

    http = FakeCloudflare({
        VERIFY: {"success": True, "result": {"id": "tok", "status": "active"}},
        PROBE: {"success": True, "result": [{"id": "zid-plant", "name": "plant.example"}]},
    })
    monkeypatch.setattr(cloudflare, "urlopen", http)
    marker = KEY_BYTES.decode()
    response = auth_client.post(
        CONNECT,
        {"token": TOKEN, "origin_ca_key": marker},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert marker not in response.content.decode()
    account = DnsAccount.objects.get()
    assert account.dns_token_ref
    assert account.origin_ca_key_ref == ""
    assert list(Secret.objects.filter(owner_type="dns_account").values_list(
        "owner_id", flat=True,
    )) == [account.dns_token_ref]


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_seams_still_refuse_until_planted():
    """Fail-closed until origin_ca_key_ref is set stays (I1).

    What would make this fail: constructing an issuer — or a Fake — when
    the account has a DNS token but no planted Origin-CA key.
    """
    account = _account(label="seam-unplanted")
    site = _public_site(account)
    _vault_dns_token(account)
    site.dns_zone.refresh_from_db()
    assert site.dns_zone.account.dns_token_ref
    assert not site.dns_zone.account.origin_ca_key_ref

    with pytest.raises(DeploySeamRefused, match="origin_ca_key_ref"):
        resolve_production_seams(site)
    row = Finding.objects.get(fingerprint=f"deploy-seam:{site.pk}")
    assert "origin_ca_key_ref" in row.body
    assert KEY_BYTES.decode() not in (row.body + row.title + (row.fix_action or ""))


@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_seams_construct_issuer_after_plant(auth_client, tmp_path, monkeypatch):
    """After plant, a proxied public deploy constructs the Origin-CA issuer."""
    from providers.cloudflare import CloudflareOriginCertIssuer
    from providers.fakes import FakeDnsProvider

    account = _account(label="seam-planted")
    site = _public_site(account)
    _vault_dns_token(account)
    path = _allowlisted_file(tmp_path, monkeypatch)
    response = _plant(auth_client, account, path)
    assert response.status_code == 200, response.content
    site.dns_zone.account.refresh_from_db()

    monkeypatch.setattr(
        "deploys.seams.dns_provider_for", lambda zone: FakeDnsProvider(),
    )
    dns, issuer = resolve_production_seams(site)
    assert dns is not None
    assert isinstance(issuer, CloudflareOriginCertIssuer)
