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


def test_no_acme_dns_challenge_block_is_ever_generated():
    """Hub-central DNS-01 is Phase 3b; Caddy must not grow an ACME DNS block.

    What would make this fail: emitting challenges.dns / acme_dns / letsencrypt
    so a token would have a place to live on the target.
    """
    _site, deployment, transport = _simulate_deploy("acmescan")
    blobs = _artifact_and_generated(deployment, transport) + _put_payloads(transport)
    for blob in blobs:
        text = _blobify(blob).decode("utf-8", "replace").lower()
        for marker in ACME_MARKERS:
            assert marker not in text, f"ACME/DNS-01 marker {marker!r} was generated"
