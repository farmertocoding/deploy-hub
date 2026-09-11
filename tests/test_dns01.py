"""Phase 7.4 T1: Hub-central DNS-01 issue + Beat renew (C1–C5, C7).

TLS-B2 is marked on the issue/refuse/renew functions. Do not mark
P7-DNS01-DEMO. Default dns01 is refuse-closed; tests inject. No live
Let's Encrypt.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from django.conf import settings
from django.utils import timezone
from test_origin_certs import TlsTransport, _desired, _site

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
DNS01_PY = REPO / "deploys" / "dns01.py"
BANNED_SOURCE = (
    "HUB_TEST_CF_TOKEN",
    "HUB_WEBHOOK_SECRET",
    "tls.issuance",
    "acme_dns",
    "dns_challenge",
    "letsencrypt",
    "zerossl",
    "dns-01",
)
TLS_DIR = "/srv/sites/{slug}/tls"


def _dns01(zone):
    """Injected issuer: upsert TXT via dns, mint a local leaf from the CSR."""

    def dns01(hostnames, csr, dns):
        from vault.tls import mint_local_leaf

        for host in hostnames:
            dns.upsert_record(
                zone,
                f"_acme-challenge.{host}",
                "TXT",
                ["hub-dns01-t1"],
                proxied=False,
            )
        certificate, expires_at = mint_local_leaf(
            csr, hostnames, validity_days=90,
        )
        return {"certificate": certificate, "expires_at": expires_at}

    return dns01


def _unproxied_desired(site, transport, **extra):
    from providers.fakes import FakeDnsProvider

    dns = extra.pop("dns", FakeDnsProvider())
    desired = _desired(site, transport, dns=dns, **extra)
    return desired, dns


@pytest.mark.req("TLS-B2-HUB-DNS01-UNPROXIED")
def test_unproxied_injected_dns01_issues_hub_mode():
    """Injected dns01 upserts TXT, pushes PEM, mode hub_dns01, no token on target.

    What would make this fail: calling Origin CA, writing a token into
    transport put/run, or leaving TlsCertificate.mode as origin_cert.
    """
    from core.models import TlsCertificate
    from deploys.certs import ensure_site_certificate
    from vault.models import Secret

    site = _site(slug="dns01-ok", proxied=False)
    transport = TlsTransport()
    issuer = _desired(site, transport)["cert_issuer"]
    desired, dns = _unproxied_desired(
        site, transport, cert_issuer=issuer, dns01=_dns01(site.dns_zone),
    )
    ensure_site_certificate(desired)

    row = TlsCertificate.objects.get(site=site)
    assert row.mode == TlsCertificate.Mode.HUB_DNS01
    assert issuer.calls == []
    upserts = [call for call in dns.calls if call[0] == "upsert_record"]
    assert upserts, "dns01 must upsert TXT through dns.upsert_record"
    names = {call[2] for call in upserts}
    assert f"_acme-challenge.{site.domain}" in names
    assert all(call[3] == "TXT" for call in upserts)
    assert all(call[5] is False for call in upserts)

    tls = TLS_DIR.format(slug=site.name)
    assert transport.files.get(f"{tls}/cert.pem")
    assert transport.files.get(f"{tls}/key.pem")
    assert Secret.objects.filter(kind=Secret.Kind.TLS_PRIVATE_KEY).exists()

    for _kind, payload in transport.calls:
        blob = payload if isinstance(payload, str) else str(payload)
        assert "HUB_TEST_CF_TOKEN" not in blob
        assert "HUB_WEBHOOK_SECRET" not in blob
        assert "cf-dns" not in blob.lower()
    for path, content in transport.files.items():
        text = content.decode() if isinstance(content, (bytes, bytearray)) else str(content)
        assert "HUB_TEST_CF_TOKEN" not in text
        assert "token" not in path.lower()
        if path.endswith(".pem") or path.endswith(".tmp"):
            assert "BEGIN" in text


@pytest.mark.req("TLS-B2-HUB-DNS01-UNPROXIED")
def test_missing_dns01_refuses_with_finding():
    """No inject → Dns01Error('dns01 refused'), Finding, no put.

    What would make this fail: a bare exception, wrapping the error, or
    putting PEM before the refuse-closed seam.
    """
    from core.models import Finding, TlsCertificate
    from deploys.certs import UnproxiedCertUnsupported, ensure_site_certificate
    from deploys.dns01 import Dns01Error

    site = _site(slug="dns01-miss", proxied=False)
    transport = TlsTransport()
    desired, _dns = _unproxied_desired(site, transport)
    assert issubclass(Dns01Error, RuntimeError)
    assert not issubclass(Dns01Error, UnproxiedCertUnsupported)
    with pytest.raises(Dns01Error, match="dns01 refused"):
        ensure_site_certificate(desired)

    row = Finding.objects.get(fingerprint=f"unproxied-cert:{site.pk}")
    assert row.severity == Finding.Severity.P2
    assert row.state == Finding.State.OPEN
    assert not TlsCertificate.objects.filter(site=site).exists()
    assert transport.mutating_calls() == []
    assert not any(kind == "put" for kind, _ in transport.calls)


@pytest.mark.req("TLS-B2-HUB-DNS01-UNPROXIED")
def test_issue_resolves_open_unproxied_finding():
    """Successful issue resolves OPEN/ACKED unproxied-cert:{pk}; ACCEPTED stays.

    What would make this fail: leaving the refusal OPEN, resolving ACCEPTED,
    or filing a second fingerprint.
    """
    from core.findings import accept_risk, ack, finding
    from core.models import Finding
    from deploys.dns01 import issue_unproxied

    open_site = _site(slug="dns01-open", proxied=False)
    acked_site = _site(slug="dns01-acked", proxied=False)
    accepted_site = _site(slug="dns01-acc", proxied=False)
    for site, state in (
        (open_site, Finding.State.OPEN),
        (acked_site, Finding.State.ACKED),
        (accepted_site, Finding.State.ACCEPTED),
    ):
        row = finding(
            "tls",
            f"unproxied-cert:{site.pk}",
            workspace=site.project.workspace,
            severity=Finding.Severity.P2,
            entity=f"site:{site.name}",
            title="Unproxied public site cannot get a Hub-issued certificate",
            body=f"{site.domain} is public with proxied=false.",
            fix_action="Enable Cloudflare proxy (proxied=true).",
        )
        if state == Finding.State.ACKED:
            ack(row, source="system")
        elif state == Finding.State.ACCEPTED:
            accept_risk(row, "operator accepted until DNS-01", source="system")

    for site in (open_site, acked_site, accepted_site):
        transport = TlsTransport()
        desired, _dns = _unproxied_desired(site, transport)
        issue_unproxied(desired, dns01=_dns01(site.dns_zone))

    assert Finding.objects.get(
        fingerprint=f"unproxied-cert:{open_site.pk}",
    ).state == Finding.State.RESOLVED
    assert Finding.objects.get(
        fingerprint=f"unproxied-cert:{acked_site.pk}",
    ).state == Finding.State.RESOLVED
    assert Finding.objects.get(
        fingerprint=f"unproxied-cert:{accepted_site.pk}",
    ).state == Finding.State.ACCEPTED


@pytest.mark.req("TLS-B2-HUB-DNS01-UNPROXIED")
def test_renew_due_reissues_inside_window():
    """hub_dns01 rows inside RENEW_BEFORE_DAYS call issue=; CheckRun.HUB_DNS01.

    What would make this fail: walking origin_cert rows, skipping the due
    row, or writing a different CheckRun kind.
    """
    from datetime import timedelta

    from core.models import CheckRun, TlsCertificate
    from deploys.certs import RENEW_BEFORE_DAYS
    from deploys.dns01 import renew_due

    now = timezone.now()
    due_site = _site(slug="dns01-due", proxied=False)
    fresh_site = _site(slug="dns01-fresh", proxied=False)
    origin_site = _site(slug="dns01-origin", proxied=True)
    due = TlsCertificate.objects.create(
        site=due_site,
        mode=TlsCertificate.Mode.HUB_DNS01,
        not_after=now + timedelta(days=RENEW_BEFORE_DAYS - 1),
        fingerprint="a" * 64,
        key_ref="site-due-tls",
        pushed_at=now,
    )
    TlsCertificate.objects.create(
        site=fresh_site,
        mode=TlsCertificate.Mode.HUB_DNS01,
        not_after=now + timedelta(days=RENEW_BEFORE_DAYS + 10),
        fingerprint="b" * 64,
        key_ref="site-fresh-tls",
        pushed_at=now,
    )
    TlsCertificate.objects.create(
        site=origin_site,
        mode=TlsCertificate.Mode.ORIGIN_CERT,
        not_after=now + timedelta(days=2),
        fingerprint="c" * 64,
        key_ref="site-origin-tls",
        pushed_at=now,
    )

    called = []

    def issue(row):
        called.append(row.pk)

    run = renew_due(now=now, issue=issue)
    assert called == [due.pk]
    assert run.kind == CheckRun.Kind.HUB_DNS01
    assert run.status == CheckRun.Status.SUCCEEDED
    assert run.results.get("schema_version") == 1
    assert CheckRun.objects.filter(kind=CheckRun.Kind.HUB_DNS01).exists()


def test_unproxied_ensure_skips_when_hub_dns01_still_fresh():
    """A second ensure of a still-fresh hub_dns01 does not create another row.

    What would make this fail: every injected call create()-ing TlsCertificate
    so renew_due later walks a pile of historical rows.
    """
    from core.models import TlsCertificate
    from deploys.certs import ensure_site_certificate

    site = _site(slug="dns01-fresh-skip", proxied=False)
    transport = TlsTransport()
    desired, _dns = _unproxied_desired(
        site, transport, dns01=_dns01(site.dns_zone),
    )
    first = ensure_site_certificate(desired)
    assert first["status"] == "issued"
    transport.calls.clear()
    second = ensure_site_certificate(desired)
    assert second["status"] == "skipped"
    assert second["id"] == first["id"]
    assert TlsCertificate.objects.filter(site=site).count() == 1
    assert transport.mutating_calls() == []


def test_renew_due_default_writes_failed_when_refused():
    """Default renew_due() (no issue=) on a due row is FAILED, not SUCCEEDED.

    What would make this fail: writing SUCCEEDED with errors on total refuse,
    so Beat hides that every row Dns01Error'd.
    """
    from datetime import timedelta

    from core.models import CheckRun, TlsCertificate
    from deploys.certs import RENEW_BEFORE_DAYS
    from deploys.dns01 import renew_due

    now = timezone.now()
    site = _site(slug="dns01-beat-fail", proxied=False)
    due = TlsCertificate.objects.create(
        site=site,
        mode=TlsCertificate.Mode.HUB_DNS01,
        not_after=now + timedelta(days=RENEW_BEFORE_DAYS - 1),
        fingerprint="d" * 64,
        key_ref="site-beat-fail-tls",
        pushed_at=now,
    )
    run = renew_due(now=now)
    assert run.kind == CheckRun.Kind.HUB_DNS01
    assert run.status == CheckRun.Status.FAILED
    assert run.status != CheckRun.Status.SUCCEEDED
    assert due.pk in run.results.get("errors", [])
    assert run.results.get("renewed") == []


def test_renew_due_uses_latest_hub_dns01_per_site():
    """Only the latest hub_dns01 row per site is considered for renew.

    What would make this fail: walking every historical hub_dns01 row so an
    old due leaf reissues while the latest is still fresh.
    """
    from datetime import timedelta

    from core.models import CheckRun, TlsCertificate
    from deploys.certs import RENEW_BEFORE_DAYS
    from deploys.dns01 import renew_due

    now = timezone.now()
    site = _site(slug="dns01-latest", proxied=False)
    old = TlsCertificate.objects.create(
        site=site,
        mode=TlsCertificate.Mode.HUB_DNS01,
        not_after=now + timedelta(days=2),
        fingerprint="e" * 64,
        key_ref="site-latest-tls",
        pushed_at=now - timedelta(days=10),
    )
    TlsCertificate.objects.create(
        site=site,
        mode=TlsCertificate.Mode.HUB_DNS01,
        not_after=now + timedelta(days=RENEW_BEFORE_DAYS + 10),
        fingerprint="f" * 64,
        key_ref="site-latest-tls",
        pushed_at=now,
    )
    due_site = _site(slug="dns01-latest-due", proxied=False)
    TlsCertificate.objects.create(
        site=due_site,
        mode=TlsCertificate.Mode.HUB_DNS01,
        not_after=now + timedelta(days=1),
        fingerprint="g" * 64,
        key_ref="site-latest-due-tls",
        pushed_at=now - timedelta(days=10),
    )
    latest_due = TlsCertificate.objects.create(
        site=due_site,
        mode=TlsCertificate.Mode.HUB_DNS01,
        not_after=now + timedelta(days=2),
        fingerprint="h" * 64,
        key_ref="site-latest-due-tls",
        pushed_at=now,
    )
    called = []

    def issue(row):
        called.append(row.pk)

    run = renew_due(now=now, issue=issue)
    assert old.pk not in called
    assert called == [latest_due.pk]
    assert run.status == CheckRun.Status.SUCCEEDED


@pytest.mark.req("TLS-B2-HUB-DNS01-UNPROXIED")
def test_module_has_no_acme_caddy_block():
    """dns01.py must not grow a Caddy ACME DNS block or invented token env.

    What would make this fail: tls.issuance / dns-01 plugin strings, or
    naming HUB_TEST_CF_TOKEN / HUB_WEBHOOK_SECRET in the module.
    """
    source = DNS01_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DNS01_PY))
    for token in BANNED_SOURCE:
        assert token not in source, f"deploys/dns01.py names {token}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            for token in BANNED_SOURCE:
                assert token not in value, f"string {value!r} contains {token}"
            lowered = value.lower()
            assert "tls.issuance" not in lowered
            assert "acme_dns" not in lowered


@pytest.mark.req("TLS-B2-HUB-DNS01-UNPROXIED")
def test_beat_hub_dns01_renew_daily_is_registered():
    """hub-dns01-renew-daily is 86400s on queue probes with no secret kwargs.

    What would make this fail: missing the Beat key, a crontab hour, or
    smuggling a token through kwargs.
    """
    from monitor import tasks as monitor_tasks

    entry = settings.CELERY_BEAT_SCHEDULE["hub-dns01-renew-daily"]
    assert entry["task"] == monitor_tasks.renew_hub_dns01.name
    assert float(entry["schedule"]) == 86400.0
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "control"
    assert "kwargs" not in entry
    assert "args" not in entry
    dumped = str(entry)
    assert "HUB_TEST_CF_TOKEN" not in dumped
    assert "HUB_WEBHOOK_SECRET" not in dumped
    assert "token" not in dumped.lower()
