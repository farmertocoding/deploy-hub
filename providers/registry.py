"""dns_provider_for(zone) and edge_protection_for(zone) — the ONLY Cloudflare
client constructors (D-033, D-057). CustomHostname create/status/TXT live on
the DnsProvider this function returns (D-079); helpers must not construct a
second client.

Scope is enforced synchronously, before the client is usable (D-034 panel r2):

  (a) Bearer only — a Global API Key credential shape is refused before any
      request (refuse_global_api_key);
  (b) `GET /user/tokens/verify` must return success plus result.status ==
      "active";
      (c) the zone-authorization probe `GET /zones?per_page=50` must report
      set size 1 (result_info.total_count when present, else len(result))
      and that one zone's id must equal DnsZone.provider_zone_id — more,
      fewer, or a mismatch refuses. A one-row page is not one zone.
      verify alone cannot prove scope: it returns no policy set (D-046);
  (d) the purpose wall — under HUB_TEST_MODE only a triple-keyed test zone
      (HUB_TEST_MODE + purpose=test + HUB_TEST_ZONE_SLUGS); outside it,
      never a purpose=test zone.

A passed verification is cached per (token_ref, resolved vault Secret, zone)
for a bounded TTL and re-verified on expiry or on any auth error mid-use.
The Secret pk in the key is what makes rotation safe: storing a new token
under the same dns_token_ref changes the key, so the never-probed new token
re-verifies instead of inheriting the old token's pass — D-034's "no code
path holds an over-scoped client" wins over any per-ref shortcut. A
verification failure fails closed and files a Finding. Tokens are loaded
from the vault by the owner-id ref on DnsAccount — refs, never values, live
from core.models import default_workspace
on the model.
"""
import time

from django.conf import settings

from core.test_mode import assert_test_zone

from . import cloudflare
from .cloudflare import (
    CloudflareDnsProvider,
    CloudflareEdge,
    CloudflareError,
    refuse_global_api_key,
    refuse_origin_ca_service_key,
)

VERIFY_TTL_S = 900.0  # 15 min: the fail-closed re-verify window

_verified = {}  # (token_ref, secret_pk, zone_pk) -> monotonic time of the last pass


class ScopeError(RuntimeError):
    """Fail-closed refusal: the client never came into existence."""


def reset_scope_cache():
    _verified.clear()


def load_aws_credentials(*, reason="aws client construction"):
    """Vault-ref explicit keys for the Hub AWS user. Never the default chain.

    Loader only — cloud_provider_for lands in Task 3. boto3 stays in
    providers/aws_creds.py.
    """
    from .aws_creds import load_credentials

    return load_credentials(reason=reason)


def dns_provider_for(zone, *, now=time.monotonic, ttl_s=VERIFY_TTL_S):
    """Build the product DNS client for a DnsZone, or refuse.

    Every refusal raises before a client object exists; ScopeError refusals
    also file a Finding so the operator sees the broken credential without
    waiting for a deploy traceback.
    """
    _purpose_wall(zone)
    account = zone.account
    if account.provider == "route53":
        from .route53 import construct as construct_route53

        return construct_route53(zone)
    if account.provider != "cloudflare":
        raise ScopeError(
            f"no DNS provider adapter for provider {account.provider!r}"
        )
    ref = account.dns_token_ref
    if not ref:
        raise ScopeError(
            f"DnsAccount {account.label!r} has no dns_token_ref; connect the "
            "account before constructing a client"
        )
    secret_pk, raw = _load_token(ref)
    try:
        token = refuse_global_api_key(raw)
    except CloudflareError as error:
        raise ScopeError(str(error)) from None

    key = (ref, secret_pk, zone.pk)
    stamp = _verified.get(key)
    if stamp is None or now() - stamp >= ttl_s:
        _verified.pop(key, None)  # expired or absent: nothing to fall back to
        try:
            _verify_scope(token, zone)
        except (ScopeError, CloudflareError) as error:
            _file_scope_finding(zone, error)
            if isinstance(error, ScopeError):
                raise
            raise ScopeError(str(error)) from None
        _verified[key] = now()

    return CloudflareDnsProvider(
        zone, token=token, on_auth_error=lambda: _verified.pop(key, None),
    )


def _purpose_wall(zone):
    """Triple-keyed in test mode; purpose=test never constructs in prod."""
    if getattr(settings, "HUB_TEST_MODE", False):
        assert_test_zone(zone)  # HUB_TEST_MODE + purpose=test + allowlist
        return
    if zone.purpose == "test":
        raise ScopeError(
            f"refusing purpose=test zone {zone.name!r} outside HUB_TEST_MODE"
        )


def _load_token(ref, *, reason="dns scope verification"):
    """Resolve a vault owner-id ref (the Target.ssh_key_ref pattern) to the
    newest dns_account api_token secret, returning (secret_pk, token_bytes).
    The pk feeds the verification-cache key so rotation re-probes. The caller
    chooses which DnsAccount ref to pass — this helper never reads
    dns_token_ref or edge_token_ref itself (D-057)."""
    from vault import service as vault_service
    from vault.models import Secret

    secret = (
        Secret.objects.filter(
            kind=Secret.Kind.API_TOKEN, owner_type="dns_account", owner_id=ref,
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if secret is None:
        raise ScopeError(f"no api_token secret in the vault for ref {ref!r}")
    return secret.pk, vault_service.get(secret, reason=reason)


def _verify_scope(token, zone):
    """Steps (b) + (c), judged over the shared pinned observation.

    cloudflare.observe_token is the ONE spelling of the verify + zone-probe
    endpoints; Task 2's daily audit consumes the same helper, so the audit
    can never drift from the enforcement it backs up (SEC-B5). Resolved
    through the module attribute so the sharing is patchable and provable.
    """
    observed = cloudflare.observe_token(token)
    status = observed["status"]
    if status != "active":
        raise ScopeError(
            f"token verify returned status {status!r}, not 'active' — refusing"
        )

    count = observed["zone_count"]
    zones = observed["zones"]
    if count != 1:
        raise ScopeError(
            f"zone probe returned {count} zones; the DNS token must be "
            f"scoped to exactly the one zone {zone.name!r} (D-046)"
        )
    if not zones:
        raise ScopeError(
            f"zone probe reported one zone but returned no row for "
            f"{zone.name!r} — refusing"
        )
    if zones[0]["id"] != zone.provider_zone_id:
        raise ScopeError(
            f"zone probe returned id {zones[0]['id']!r}, expected "
            f"{zone.provider_zone_id!r} for {zone.name!r} — refusing"
        )


def origin_cert_issuer_for(zone):
    """Build the Origin CA issuer for a DnsZone, or refuse.

    The Origin CA credential is a Bearer API token (Zone SSL and Certificates
    Edit), not a deprecated service key. It is a different vault ref from the
    DNS token. Presence of a vaulted ref is the fail-closed construction fact;
    a v1.0- service key is shape-refused here, before a client exists.
    """
    from .cloudflare import CloudflareOriginCertIssuer

    account = zone.account
    ref = account.origin_ca_key_ref
    if not ref:
        raise ScopeError(
            f"DnsAccount {account.label!r} has no origin_ca_key_ref; connect "
            "the account before issuing an Origin certificate"
        )
    _purpose_wall(zone)
    _secret_pk, raw = _load_origin_ca_key(ref)
    try:
        token = refuse_origin_ca_service_key(raw)
        _verify_scope(token, zone)
    except CloudflareError as error:
        raise ScopeError(str(error)) from None
    return CloudflareOriginCertIssuer(zone, origin_ca_key=token)


def _load_origin_ca_key(ref):
    from vault import service as vault_service
    from vault.models import Secret

    secret = (
        Secret.objects.filter(
            kind=Secret.Kind.API_TOKEN, owner_type="dns_account", owner_id=ref,
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if secret is None:
        raise ScopeError(f"no origin CA secret in the vault for ref {ref!r}")
    return secret.pk, vault_service.get(secret, reason="origin ca issue")


def edge_protection_for(zone, *, now=time.monotonic, ttl_s=VERIFY_TTL_S):
    """Build the product EdgeProtection client for a DnsZone, or None.

    Absent edge_token_ref returns None so the playbook can degrade to
    notify-only (C3). A present ref is fail-closed like dns_provider_for:
    Bearer-only, active token, one-zone probe. Never loads the DNS token ref.
    """
    if zone is None:
        return None
    account = zone.account
    ref = account.edge_token_ref
    if not ref:
        return None
    _purpose_wall(zone)
    if account.provider != "cloudflare":
        raise ScopeError(
            f"no edge protection adapter for provider {account.provider!r}"
        )
    secret_pk, raw = _load_token(ref, reason="edge scope verification")
    try:
        token = refuse_global_api_key(raw)
    except CloudflareError as error:
        raise ScopeError(str(error)) from None

    key = ("edge", ref, secret_pk, zone.pk)
    stamp = _verified.get(key)
    if stamp is None or now() - stamp >= ttl_s:
        _verified.pop(key, None)
        try:
            _verify_scope(token, zone)
        except (ScopeError, CloudflareError) as error:
            _file_scope_finding(zone, error, role="edge")
            if isinstance(error, ScopeError):
                raise
            raise ScopeError(str(error)) from None
        _verified[key] = now()

    return CloudflareEdge(
        zone, token=token, on_auth_error=lambda: _verified.pop(key, None),
    )


def _file_scope_finding(zone, error, *, role="dns"):
    """A refused construction is operator-visible, not just a raise.

    Goes through raise_alert so classify() + finding() give the refusal the
    same audit + findings-topic publish as every other class. Kind is
    ``cf-token-scope`` (the table row for construction refusal and the
    daily-audit drift). The fingerprint stays the Task-1 identity
    ``cf-scope:{account_id}:{zone.name}`` — not ``cf-token-scope:{pk}:{role}``,
    which is the daily-audit row. Edge construction uses a distinct
    ``cf-scope:{account_id}:edge:{zone.name}`` so it cannot clobber DNS.
    """
    from monitor.alerts import raise_alert

    if role == "dns":
        fingerprint = f"cf-scope:{zone.account_id}:{zone.name}"
        fix = (
            "Issue a single-zone scoped DNS token and update the "
            "DnsAccount dns_token_ref"
        )
    else:
        fingerprint = f"cf-scope:{zone.account_id}:{role}:{zone.name}"
        fix = (
            "Issue a single-zone scoped edge token and update the "
            "DnsAccount edge_token_ref"
        )
    raise_alert(
        "cf-token-scope",
        f"dns_zone:{zone.name}",
        fingerprint=fingerprint,
        workspace=zone.account.workspace,
        source_engine="dns_scope",
        title=f"Cloudflare scope verification failed for {zone.name}",
        body=str(error),
        fix_action=fix,
    )


def cloud_provider_for(*, region_name="us-east-1", **kwargs):
    """The only CloudProvider constructor (D-068). Fail-closed.

    Loads vault-ref credentials via load_aws_credentials, observes
    sts:GetCallerIdentity, applies the AWS test-plane wall, and returns
    Ec2CloudProvider. boto3 stays in aws_creds / ec2 — never imported here.
    """
    from core.test_mode import assert_test_aws

    from .aws_creds import boto3_client
    from .ec2 import Ec2CloudProvider

    creds = load_aws_credentials(reason="ec2 client construction")
    sts = boto3_client(
        "sts",
        access_key_id=creds["access_key_id"],
        secret_access_key=creds["secret_access_key"],
        region_name=region_name,
    )
    try:
        ident = sts.get_caller_identity()
    except Exception as exc:
        raise ScopeError("sts:GetCallerIdentity failed") from exc
    account_id = str(ident["Account"])
    assert_test_aws(account_id, region_name)
    client = boto3_client(
        "ec2",
        access_key_id=creds["access_key_id"],
        secret_access_key=creds["secret_access_key"],
        region_name=region_name,
    )
    return Ec2CloudProvider(
        client,
        region_name=region_name,
        account_id=account_id,
        **kwargs,
    )


def image_registry_for(desired=None):
    """Return an ImageRegistry, or None so ensure_ship docker-loads.

    Unconfigured (default ship_mode load) returns None — never an open
    registry. A ship_mode=registry request is built in
    providers.image_registry (fail-closed), not here.
    """
    desired = desired or {}
    body = desired.get("manifest_body") or {}
    raw = desired.get("ship_mode")
    if raw is None:
        raw = body.get("ship_mode")
    mode = str(raw or "load").strip() or "load"
    if mode == "load":
        return None
    from .image_registry import ImageRegistryError
    from .image_registry import build as build_image_registry

    if mode != "registry":
        raise ScopeError(
            f"unknown ship_mode {mode!r}; expected load or registry"
        )
    try:
        return build_image_registry(desired)
    except ImageRegistryError as error:
        raise ScopeError(str(error)) from None


def ssm_for(target):
    """Product SSM client for a Target. Fail-closed via Task 2's loader."""
    from .aws_creds import AwsCredsError
    from .ssm import SsmClient, SsmError

    if target is None or getattr(target, "pk", None) is None:
        raise SsmError("ssm_for requires a Target")
    try:
        creds = load_aws_credentials(reason="ssm client construction")
    except AwsCredsError as exc:
        raise SsmError(str(exc)) from None
    return SsmClient(
        target=target,
        access_key_id=creds["access_key_id"],
        secret_access_key=creds["secret_access_key"],
    )


def git_visibility_for(project):
    """Read-only Git visibility adapter, or None if unconfigured.

    No default SDK / GitHub credential chain. Tests inject this function.
    A live GitHub client is not shipped this wave.
    """
    if getattr(project, "source_kind", None) != "git":
        return None
    if not getattr(project, "git_url", None):
        return None
    return None
