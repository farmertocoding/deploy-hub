"""D-035: cert_refusal on GET /api/v1/projects/ from the open Finding (I2)."""
import pytest
from dns_fixtures import default_dns_zone

from core.findings import finding
from core.models import Finding, Project, Site

pytestmark = pytest.mark.django_db


def _enrolled_client(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(
        user=User.objects.get(username="joseph"), name="phone", confirmed=True,
    )
    client.login(username="joseph", password="a-long-dev-password")


def test_project_row_emits_cert_refusal_from_open_unproxied_finding(client):
    """Sites.jsx CertState reads site.cert_refusal; the list payload must carry it.

    What would make this fail: project_row_body omitting the field so live
    Sites never shows the refusal the Finding already holds.
    """
    project = Project.objects.create(name="refuse-me", slug="refuse-me")
    site = Site.objects.create(
        project=project, name="bare", domain="bare.example.test",
        dns_zone=default_dns_zone("bare.example.test"), proxied=False,
    )
    row = finding(
        "tls",
        f"unproxied-cert:{site.pk}",
        workspace=site.project.workspace,
        severity=Finding.Severity.P2,
        entity=f"site:{site.name}",
        title="Unproxied public site cannot get a Hub-issued certificate",
        body="bare.example.test is public with proxied=false.",
        fix_action="Enable Cloudflare proxy (proxied=true).",
    )

    _enrolled_client(client)
    payload = client.get("/api/v1/projects/").json()
    listed = next(p for p in payload if p["slug"] == "refuse-me")
    refusal = listed["sites"][0]["cert_refusal"]
    assert refusal["finding_id"] == row.pk
    assert "proxied=false" in refusal["detail"] or "Unproxied" in refusal["detail"]


def test_project_row_cert_refusal_is_null_without_an_open_finding(client):
    """No open unproxied-cert:{pk} Finding → cert_refusal is null, not omitted."""
    project = Project.objects.create(name="clean-tls", slug="clean-tls")
    Site.objects.create(
        project=project, name="ok", domain="ok.example.test",
        dns_zone=default_dns_zone("ok.example.test"),
    )
    _enrolled_client(client)
    listed = next(
        p for p in client.get("/api/v1/projects/").json() if p["slug"] == "clean-tls"
    )
    assert listed["sites"][0]["cert_refusal"] is None
