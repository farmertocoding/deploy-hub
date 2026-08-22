"""dns_provider_for(zone) — the ONLY DNS-client construction path (D-033).

Scope is enforced synchronously, before the client is usable (D-034 panel r2):

  (a) Bearer only — a Global API Key credential shape is refused before any
      request (refuse_global_api_key);
  (b) `GET /user/tokens/verify` must return success plus result.status ==
      "active";
  (c) the zone-authorization probe `GET /zones?per_page=50` must return
      EXACTLY one zone whose id equals DnsZone.provider_zone_id — more,
      fewer, or a mismatch refuses. verify alone cannot prove scope: it
      returns no policy set (D-046);
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
on the model.
"""
import time

from django.conf import settings

from core.test_mode import assert_test_zone

from . import cloudflare
from .cloudflare import (
    CloudflareDnsProvider,
    CloudflareError,
    refuse_global_api_key,
)

VERIFY_TTL_S = 900.0  # 15 min: the fail-closed re-verify window

_verified = {}  # (token_ref, secret_pk, zone_pk) -> monotonic time of the last pass


class ScopeError(RuntimeError):
    """Fail-closed refusal: the client never came into existence."""


def reset_scope_cache():
    _verified.clear()


def dns_provider_for(zone, *, now=time.monotonic, ttl_s=VERIFY_TTL_S):
    """Build the product DNS client for a DnsZone, or refuse.

    Every refusal raises before a client object exists; ScopeError refusals
    also file a Finding so the operator sees the broken credential without
    waiting for a deploy traceback.
    """
    _purpose_wall(zone)
    account = zone.account
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


def _load_token(ref):
    """Resolve a vault owner-id ref (the Target.ssh_key_ref pattern) to the
    newest dns_account api_token secret, returning (secret_pk, token_bytes).
    The pk feeds the verification-cache key so rotation re-probes."""
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
    return secret.pk, vault_service.get(secret, reason="dns scope verification")


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

    zones = observed["zones"]
    if len(zones) != 1:
        raise ScopeError(
            f"zone probe returned {len(zones)} zones; the DNS token must be "
            f"scoped to exactly the one zone {zone.name!r} (D-046)"
        )
    if zones[0]["id"] != zone.provider_zone_id:
        raise ScopeError(
            f"zone probe returned id {zones[0]['id']!r}, expected "
            f"{zone.provider_zone_id!r} for {zone.name!r} — refusing"
        )


def _file_scope_finding(zone, error):
    """A refused construction is operator-visible, not just a raise.

    Goes through raise_alert so classify() + finding() give the refusal the
    same audit + findings-topic publish as every other class. Kind is
    ``cf-token-scope`` (the table row for construction refusal and the
    daily-audit drift). The fingerprint stays the Task-1 identity
    ``cf-scope:{account_id}:{zone.name}`` — not ``cf-token-scope:{pk}:{role}``,
    which is the daily-audit row.
    """
    from monitor.alerts import raise_alert

    raise_alert(
        "cf-token-scope",
        f"dns_zone:{zone.name}",
        fingerprint=f"cf-scope:{zone.account_id}:{zone.name}",
        source_engine="dns_scope",
        title=f"Cloudflare scope verification failed for {zone.name}",
        body=str(error),
        fix_action=(
            "Issue a single-zone scoped DNS token and update the "
            "DnsAccount dns_token_ref"
        ),
    )
