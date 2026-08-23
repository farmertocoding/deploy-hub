"""SEC-B2-NO-TOKEN-ON-TARGET: every target-bound surface is scanned (D-035).

The scan takes the live token values, the vault refs, and the env-var names
and runs them over a full simulated deploy — not a spot check of two files.
"""
from __future__ import annotations

import json

import pytest
from pipeline_fakes import PipelineTransport, fixture_body, queued_deployment

pytestmark = [pytest.mark.django_db, pytest.mark.req("SEC-B2-NO-TOKEN-ON-TARGET")]

DNS_TOKEN = "cf-dns-t1-planted-token-do-not-exfiltrate-9f3a"  # nosec B105
EDGE_TOKEN = "cf-edge-t1-planted-token-do-not-exfiltrate-7b2c"  # nosec B105
OCA_KEY = "cf-oca-t1-planted-key-do-not-exfiltrate-4d1e"  # nosec B105
DNS_REF = "vault-ref-dns-PLANTED"
EDGE_REF = "vault-ref-edge-PLANTED"
OCA_REF = "vault-ref-oca-PLANTED"
ENV_NAMES = (
    "CF_API_TOKEN",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_DNS_API_TOKEN",
    "CLOUDFLARE_ORIGIN_CA_KEY",
    "CF_ORIGIN_CA_KEY",
)
SECRETS = (DNS_TOKEN, EDGE_TOKEN, OCA_KEY, DNS_REF, EDGE_REF, OCA_REF, *ENV_NAMES)
ACME_MARKERS = (
    "dns_challenge",
    "dns01",
    "acme_dns",
    "tls.issuance",
    "letsencrypt",
    "zerossl",
)


def _plant_credentials(site):
    from vault import service as vault_service

    account = site.dns_zone.account
    vault_service.put(
        kind="api_token", owner_type="dns_account", owner_id=DNS_REF,
        plaintext=DNS_TOKEN.encode(),
    )
    vault_service.put(
        kind="api_token", owner_type="dns_account", owner_id=EDGE_REF,
        plaintext=EDGE_TOKEN.encode(),
    )
    vault_service.put(
        kind="api_token", owner_type="dns_account", owner_id=OCA_REF,
        plaintext=OCA_KEY.encode(),
    )
    account.dns_token_ref = DNS_REF
    account.edge_token_ref = EDGE_REF
    account.origin_ca_key_ref = OCA_REF
    account.save()


def _env_bundle(slug):
    from vault import service as vault_service
    from vault.models import Secret

    return vault_service.put(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type="manifest",
        owner_id=f"exfil-{slug}",
        plaintext=json.dumps({"APP_SECRET": "app-only-not-a-dns-token"}).encode(),
    )


def _simulate_deploy(slug="exfil"):
    from deploys.pipeline import execute
    from providers.fakes import FakeDnsProvider, FakeOriginCertIssuer

    bundle = _env_bundle(slug)
    body = fixture_body(slug)
    body["env_bundle_ref"] = bundle.pk
    body["env_names"] = ["APP_SECRET"]
    site, deployment = queued_deployment(slug, body=body)
    _plant_credentials(site)
    transport = PipelineTransport()
    execute(
        deployment.pk,
        transport=transport,
        dns=FakeDnsProvider(),
        cert_issuer=FakeOriginCertIssuer(),
    )
    deployment.refresh_from_db()
    return site, deployment, transport


def _blobify(value):
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, default=str).encode()
    return str(value).encode()


def _put_payloads(transport):
    return list(transport.files.values())


def _run_argv_blobs(transport):
    return [
        _blobify(payload)
        for kind, payload in transport.calls
        if kind == "run"
    ]


def _env_surfaces(deployment, transport):
    from deploys.pipeline import load_env_snapshot

    blobs = []
    snapshot = load_env_snapshot(deployment)
    if snapshot is not None:
        blobs.append(snapshot if isinstance(snapshot, (bytes, bytearray)) else snapshot)
    for remote, content in transport.files.items():
        name = str(remote)
        if name.endswith(".env") or "/env" in name or name.endswith(".env.snapshot"):
            blobs.append(content)
    return blobs


def _artifact_and_generated(deployment, transport):
    from deploys.models import DeploymentArtifact

    blobs = []
    for row in DeploymentArtifact.objects.filter(deployment=deployment):
        blobs.append(row.content)
    for remote, content in transport.files.items():
        name = str(remote)
        if name.endswith(".json") or "caddy" in name or "Dockerfile" in name:
            blobs.append(content)
    return blobs


def _call_log_blob(transport):
    return _blobify([(kind, payload) for kind, payload in transport.calls])


def _assert_clean(blobs, *, where):
    for blob in blobs:
        raw = _blobify(blob)
        text = raw.decode("utf-8", "replace")
        for secret in SECRETS:
            assert secret not in text, f"{where} leaked {secret!r}"
            assert secret.encode() not in raw, f"{where} leaked bytes of {secret!r}"


def test_no_dns_token_in_put_payloads():
    """What would make this fail: a put() of the DNS/edge/Origin-CA value."""
    _site, deployment, transport = _simulate_deploy("putscan")
    assert deployment.status == "succeeded"
    _assert_clean(_put_payloads(transport), where="put payload")


def test_no_dns_token_in_run_argv():
    """What would make this fail: interpolating a token into a remote argv."""
    _site, deployment, transport = _simulate_deploy("argvscan")
    assert deployment.status == "succeeded"
    _assert_clean(_run_argv_blobs(transport), where="run argv")


def test_no_dns_token_in_env_files_or_env_snapshots():
    """What would make this fail: CF_API_TOKEN=... in the env file or snapshot."""
    _site, deployment, transport = _simulate_deploy("envscan")
    assert deployment.status == "succeeded"
    _assert_clean(_env_surfaces(deployment, transport), where="env file/snapshot")


def test_no_dns_token_in_celery_task_kwargs():
    """What would make this fail: a token or vault ref in run_deploy kwargs."""
    from deploys.tasks import run_deploy

    _site, deployment, _transport = _simulate_deploy("celeryscan")
    sig = run_deploy.s(deployment.pk)
    _assert_clean([sig.args, sig.kwargs, sig.options], where="celery signature")
    # The Beat entries that already exist must not grow credential kwargs.
    from django.conf import settings

    _assert_clean(
        [settings.CELERY_BEAT_SCHEDULE],
        where="CELERY_BEAT_SCHEDULE",
    )


def test_no_dns_token_in_deployment_artifacts_or_manifest():
    """What would make this fail: a token in an artifact body or Manifest.body."""
    from deploys.models import DeploymentArtifact

    _site, deployment, _transport = _simulate_deploy("artscan")
    blobs = [deployment.manifest.body]
    blobs.extend(
        row.content
        for row in DeploymentArtifact.objects.filter(deployment=deployment)
    )
    _assert_clean(blobs, where="artifact/manifest")


def test_no_dns_token_in_generated_caddy_or_dockerfile_text():
    """What would make this fail: baking a token into Caddy JSON or a Dockerfile."""
    _site, deployment, transport = _simulate_deploy("cfgsan")
    _assert_clean(_artifact_and_generated(deployment, transport), where="caddy/dockerfile")


def test_recorded_transport_call_log_is_token_free():
    """What would make this fail: the call log itself carrying a token string."""
    _site, deployment, transport = _simulate_deploy("logscan")
    _assert_clean([_call_log_blob(transport)], where="transport call log")


class _FactoryHttp:
    """Wall-style urlopen double plus Origin-CA mint from the Hub CSR.

    ``FakeCloudflare.__call__`` lives on the class, so a per-instance
    assignment would never run — this wrapper owns ``__call__``.
    """

    def __init__(self, zone):
        from test_cloudflare_adapter import FakeCloudflare, list_page, record

        zid = zone.provider_zone_id
        self._http = FakeCloudflare({
            ("GET", "/user/tokens/verify"): {
                "success": True, "result": {"id": "tok-1", "status": "active"},
            },
            ("GET", "/zones?per_page=50"): {
                "success": True,
                "result": [{"id": zid, "name": zone.name}],
            },
            ("GET", f"/zones/{zid}/dns_records?per_page=100&page=1"): list_page([]),
            ("POST", f"/zones/{zid}/dns_records"): {
                "success": True,
                "result": record("rec1", f"factory.{zone.name}", "127.0.0.1"),
            },
        })

    @property
    def requests(self):
        return self._http.requests

    def __call__(self, request, timeout=None):
        from test_cloudflare_adapter import _Resp

        from providers.cloudflare import API
        from vault.tls import mint_local_leaf

        path = request.full_url[len(API):]
        if request.get_method() == "POST" and path == "/certificates":
            payload = json.loads(request.data.decode())
            certificate, expires_at = mint_local_leaf(
                payload["csr"],
                payload["hostnames"],
                validity_days=int(payload.get("requested_validity") or 5475),
            )
            self._http.requests.append((
                "POST", path, dict(request.header_items()), request.data.decode(),
            ))
            return _Resp({
                "success": True,
                "result": {
                    "certificate": certificate,
                    "expires_on": expires_at.isoformat(),
                },
            })
        return self._http(request, timeout=timeout)


def _track_fakes(monkeypatch):
    import providers.fakes as fakes

    counts = {"dns": 0, "issuer": 0}
    real_dns = fakes.FakeDnsProvider.__init__
    real_issuer = fakes.FakeOriginCertIssuer.__init__

    def dns_init(self, *args, **kwargs):
        counts["dns"] += 1
        return real_dns(self, *args, **kwargs)

    def issuer_init(self, *args, **kwargs):
        counts["issuer"] += 1
        return real_issuer(self, *args, **kwargs)

    monkeypatch.setattr(fakes.FakeDnsProvider, "__init__", dns_init)
    monkeypatch.setattr(fakes.FakeOriginCertIssuer, "__init__", issuer_init)
    return counts


def test_factory_path_leaves_target_bound_blobs_clean(monkeypatch):
    """Same planted secrets, production seams: execute(pk, transport=...).

    What would make this fail: a token riding the registry-constructed
    client onto put/run/env/artifacts/celery/call-log — the Fake-injected
    scan cannot see that path.
    """
    import providers.cloudflare as cloudflare
    import providers.registry as registry
    from deploys.pipeline import execute
    from deploys.tasks import run_deploy

    registry.reset_scope_cache()
    fake_counts = _track_fakes(monkeypatch)

    bundle = _env_bundle("factoryscan")
    body = fixture_body("factoryscan")
    body["env_bundle_ref"] = bundle.pk
    body["env_names"] = ["APP_SECRET"]
    site, deployment = queued_deployment("factoryscan", body=body)
    _plant_credentials(site)
    http = _FactoryHttp(site.dns_zone)
    monkeypatch.setattr(cloudflare, "urlopen", http)
    transport = PipelineTransport()

    execute(deployment.pk, transport=transport)

    deployment.refresh_from_db()
    assert deployment.status == "succeeded"
    assert fake_counts == {"dns": 0, "issuer": 0}
    assert any(path == "/user/tokens/verify" for _method, path, *_ in http.requests)
    _assert_clean(_put_payloads(transport), where="factory put payload")
    _assert_clean(_run_argv_blobs(transport), where="factory run argv")
    _assert_clean(_env_surfaces(deployment, transport), where="factory env")
    _assert_clean([deployment.manifest.body], where="factory manifest")
    _assert_clean(
        _artifact_and_generated(deployment, transport),
        where="factory artifact/caddy",
    )
    _assert_clean([_call_log_blob(transport)], where="factory call log")
    sig = run_deploy.s(deployment.pk)
    _assert_clean([sig.args, sig.kwargs, sig.options], where="factory celery")


def _simulate_adopt(slug="adopt-exfil"):
    """Plant the same DNS/edge/Origin-CA secrets, then run adopt_flow."""
    from pathlib import Path

    from dns_fixtures import default_dns_zone
    from test_adopt_flow import AdoptTransport, _desired, _target

    from core.models import Project, Site
    from deploys.adopt_flow import adopt_flow
    from deploys.models import Deployment, Manifest
    from providers.fakes import FakeDnsProvider

    fixtures = Path(__file__).resolve().parent / "fixtures" / "compose" / "web-only"
    project = Project.objects.create(
        name=slug,
        slug=slug,
        source_kind=Project.Source.LOCAL_PATH,
        local_path=str(fixtures),
    )
    site = Site.objects.create(
        project=project,
        name=slug,
        domain=f"{slug}.example.com",
        primary_target=_target(slug),
        dns_zone=default_dns_zone(),
        proxied=True,
    )
    _plant_credentials(site)
    manifest = Manifest.objects.create(
        site=site,
        version=1,
        body={"git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    )
    deployment = Deployment.objects.create(manifest=manifest)
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    adopt_flow(_desired(site, deployment, transport, dns))
    return site, deployment, transport


def test_adopt_put_payloads_have_no_dns_tokens():
    """Adopt put() surfaces must stay clean of DNS / Origin-CA tokens and env names.

    What would make this fail: putting CF_API_TOKEN or the planted token onto
    the target during temp deploy / env-file write.
    """
    _site, _deployment, transport = _simulate_adopt("adoptput")
    _assert_clean(_put_payloads(transport), where="adopt put payload")


def test_adopt_run_argv_has_no_dns_tokens():
    """Adopt run() argv must stay clean of DNS / Origin-CA tokens and env names.

    What would make this fail: interpolating a planted token or CF_* env name
    into a remote docker/curl argv.
    """
    _site, _deployment, transport = _simulate_adopt("adoptrun")
    _assert_clean(_run_argv_blobs(transport), where="adopt run argv")


def test_no_acme_dns_challenge_block_is_ever_generated():
    """Hub-central DNS-01 is phase 4; Caddy must not grow an ACME DNS block.

    What would make this fail: emitting challenges.dns / acme_dns / letsencrypt
    so a token would have a place to live on the target.
    """
    _site, deployment, transport = _simulate_deploy("acmescan")
    blobs = _artifact_and_generated(deployment, transport) + _put_payloads(transport)
    for blob in blobs:
        text = _blobify(blob).decode("utf-8", "replace").lower()
        for marker in ACME_MARKERS:
            assert marker not in text, f"ACME/DNS-01 marker {marker!r} was generated"


@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
def test_playbook_never_puts_edge_token_on_target():
    """L5 talks to EdgeProtection on the Hub; the edge token never rides Transport.

    What would make this fail: playbook put()/run() of the planted edge token,
    or filing it on the Finding the pager will copy.
    """
    import ast
    import pathlib
    from datetime import timedelta

    from django.utils import timezone

    from core.models import AuditEvent, Finding, TrafficStat
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    repo = pathlib.Path(__file__).resolve().parent.parent
    src = (repo / "monitor" / "attack_playbook.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "transport" not in alias.name.lower()
                assert "cloudflare" not in alias.name
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "cloudflare" not in module
            assert module.split(".")[0] != "deploys"
    assert "Transport" not in src
    assert ".put(" not in src

    site = _simulate_deploy("playbook-exfil")[0]
    target = site.primary_target
    target.collect_payload = {
        "log_chunk": {"summary": {"top_ips": [["203.0.113.9", 8000]]}},
    }
    target.save(update_fields=["collect_payload"])

    now = timezone.now().replace(second=0, microsecond=0)
    for offset, requests in enumerate(reversed([10] * 20 + [8000])):
        TrafficStat.objects.create(
            site=site,
            bucket_start=now - timedelta(minutes=offset),
            granularity=TrafficStat.Granularity.MINUTE,
            requests=requests,
        )
    row = run(site, FakeEdgeProtection())
    assert row is not None
    blob = f"{row.title}\n{row.body}\n{row.fix_action}\n{row.fingerprint}"
    _assert_clean([blob], where="attack playbook finding")
    details = list(
        AuditEvent.objects.filter(object_id=str(row.pk)).values_list("detail", flat=True)
    )
    _assert_clean(details, where="attack playbook audit")
    for finding in Finding.objects.filter(pk=row.pk):
        _assert_clean(
            [finding.title, finding.body, finding.fix_action, finding.entity],
            where="attack playbook finding row",
        )
