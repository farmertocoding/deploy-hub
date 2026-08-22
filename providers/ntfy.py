"""ntfy HTTPS pager (D-036). One publish, Bearer publisher token, vault refs.

Three publisher identity classes — hub, healthchecks, target:<id> — never one
shared secret. The subscriber/read credential is a separate protected-topic
token; nothing here publishes with it. A bare topic with no token is refused.
"""
import json
from urllib.request import Request, urlopen

from django.conf import settings

from vault.models import Secret

from .base import Pager

PUBLISHER_OWNER = "ntfy"
REVOKED_OWNER = "ntfy-revoked"


class PagerAuthError(RuntimeError):
    """Publish refused: missing token or subscriber credential."""


class TokenRevoked(RuntimeError):
    """The Hub refuses to reissue a revoked publisher identity."""


def publisher_ref(identity):
    """Vault owner-id for a publisher identity class."""
    if identity == "hub":
        return settings.HUB_NTFY_PUBLISHER_HUB_REF
    if identity == "healthchecks":
        return settings.HUB_NTFY_PUBLISHER_HEALTHCHECKS_REF
    if isinstance(identity, str) and identity.startswith("target:"):
        return f"ntfy-publisher-{identity}"
    raise ValueError(f"unknown publisher identity {identity!r}")


def topic_ref(severity):
    if severity == "p1":
        return settings.HUB_NTFY_TOPIC_P1_REF
    return settings.HUB_NTFY_TOPIC_P2_REF


def _load_secret(ref):
    if not ref:
        return None
    secret = (
        Secret.objects.filter(
            kind=Secret.Kind.API_TOKEN,
            owner_type=PUBLISHER_OWNER,
            owner_id=ref,
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if secret is None:
        return None
    from vault import service as vault_service

    return vault_service.get(secret, reason="ntfy").decode().strip()


def is_revoked(identity):
    return Secret.objects.filter(
        kind=Secret.Kind.API_TOKEN,
        owner_type=REVOKED_OWNER,
        owner_id=publisher_ref(identity),
    ).exists()


def mark_revoked(identity):
    from vault import service as vault_service

    return vault_service.put(
        kind=Secret.Kind.API_TOKEN,
        owner_type=REVOKED_OWNER,
        owner_id=publisher_ref(identity),
        plaintext=b"revoked",
    )


def issue_publisher_token(identity, plaintext):
    """Issue (or refuse to reissue) a publisher token for an identity class."""
    if is_revoked(identity):
        raise TokenRevoked(f"refused: {identity} publish token was revoked")
    from vault import service as vault_service

    if not isinstance(plaintext, (bytes, bytearray)):
        plaintext = str(plaintext).encode()
    return vault_service.put(
        kind=Secret.Kind.API_TOKEN,
        owner_type=PUBLISHER_OWNER,
        owner_id=publisher_ref(identity),
        plaintext=bytes(plaintext),
    )


def revoke_via_account_api(identity):
    """Delete the token via the ntfy account API when configured.

    Returns True only when the API call ran. An empty
    HUB_NTFY_ACCOUNT_TOKEN_REF means 'not configured'.
    """
    account_ref = getattr(settings, "HUB_NTFY_ACCOUNT_TOKEN_REF", "") or ""
    if not account_ref:
        return False
    account = _load_secret(account_ref)
    token = _load_secret(publisher_ref(identity))
    if not account or not token:
        return False
    url = settings.HUB_NTFY_BASE_URL.rstrip("/") + "/v1/account/token"
    request = Request(
        url,
        data=json.dumps({"token": token}).encode(),
        headers={
            "Authorization": f"Bearer {account}",
            "Content-Type": "application/json",
        },
        method="DELETE",
    )
    # nosec B310 — URL is the configured ntfy base + a fixed path.
    urlopen(request, timeout=10)  # nosec B310
    return True


class NtfyPager(Pager):
    def publish(
        self,
        severity,
        title,
        body,
        *,
        tags,
        click_url,
        topic=None,
        token=None,
        identity="hub",
    ):
        topic = topic if topic is not None else _load_secret(topic_ref(severity))
        token = token if token is not None else _load_secret(publisher_ref(identity))
        if not token:
            raise PagerAuthError(
                "refused: cannot publish with a bare topic and no token"
            )
        subscriber = _load_secret(settings.HUB_NTFY_SUBSCRIBER_REF)
        if subscriber and token == subscriber:
            raise PagerAuthError(
                "refused: subscriber credential cannot be used to publish"
            )
        base = getattr(settings, "HUB_NTFY_BASE_URL", "https://ntfy.sh").rstrip("/")
        url = f"{base}/{topic or ''}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Title": title,
            "Priority": "max" if severity == "p1" else "default",
            "Tags": ",".join(tags) if tags else "",
            "Click": click_url or "",
        }
        request = Request(url, data=body.encode(), headers=headers, method="POST")
        # nosec B310 — topic and token come from the vault, never caller input.
        urlopen(request, timeout=10)  # nosec B310
