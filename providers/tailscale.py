"""Tailscale device-list client (D-058 / SEC-B8).

HUB_TAILSCALE_API_TOKEN_REF is a vault owner-id, never a token value. An empty
ref skips the daily poll (CheckRun SKIPPED, never SUCCEEDED) rather than
inventing a live token env. The token is Authorization only: not in repr,
Finding, CheckRun, logs, task args, or exception text. This module logs nothing.
"""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings

API = "https://api.tailscale.com/api/v2"
DEVICES_PATH = "/tailnet/-/devices"

RESULTS_SCHEMA_VERSION = 1
SOURCE_ENGINE = "tailscale_devices"
ALERT_KIND = "tailscale-unknown-device"
OWNER_TYPE = "tailscale"


class TailscaleError(RuntimeError):
    """A Tailscale call failed. Never carries the token."""


class Tailscale:
    """Product client. Tests inject FakeTailscale; Beat constructs this."""

    def __init__(self, token):
        self._token = token

    def __repr__(self):
        return "<Tailscale redacted>"

    def list_devices(self, *, timeout=20):
        request = Request(
            API + DEVICES_PATH,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        # nosec justification: the scheme is pinned — every URL is API + path
        # where API is the https:// Tailscale constant above; no caller input
        # can change the scheme to file:/ or custom.
        try:
            with urlopen(request, timeout=timeout) as response:  # nosec B310
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise TailscaleError(
                f"tailscale API GET {DEVICES_PATH} failed: HTTP {error.code}",
            ) from None
        except OSError as error:
            raise TailscaleError(
                f"tailscale API GET {DEVICES_PATH} failed: {type(error).__name__}",
            ) from None
        if not isinstance(body, dict):
            raise TailscaleError(
                f"tailscale API GET {DEVICES_PATH} failed: unexpected body",
            )
        rows = body.get("devices") or []
        return [_normalize(row) for row in rows]


def audit_devices(*, client=None):
    """List tailnet devices; skip when the vault ref is empty (D-058)."""
    from core.models import CheckRun
    from monitor.drills import record_run

    ref = (getattr(settings, "HUB_TAILSCALE_API_TOKEN_REF", "") or "").strip()
    if not ref:
        return record_run(
            CheckRun.Kind.TAILSCALE_DEVICES,
            CheckRun.Status.SKIPPED,
            {"schema_version": RESULTS_SCHEMA_VERSION, "skipped": "absent_ref"},
        )

    try:
        token = _load_token(ref)
    except TailscaleError:
        return record_run(
            CheckRun.Kind.TAILSCALE_DEVICES,
            CheckRun.Status.FAILED,
            {"schema_version": RESULTS_SCHEMA_VERSION, "error": "no_secret"},
        )

    if client is None:
        client = Tailscale(token)

    try:
        devices = client.list_devices()
    except TailscaleError as error:
        return record_run(
            CheckRun.Kind.TAILSCALE_DEVICES,
            CheckRun.Status.FAILED,
            {
                "schema_version": RESULTS_SCHEMA_VERSION,
                "error": type(error).__name__,
            },
        )

    unknown = []
    targets = _targets()
    for device in devices:
        device_id = _device_id(device)
        if not device_id:
            continue
        if _matches_hub_target(device, targets):
            continue
        unknown.append(device_id)
        _file_unknown(device, device_id)

    return record_run(
        CheckRun.Kind.TAILSCALE_DEVICES,
        CheckRun.Status.SUCCEEDED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "seen": len(devices),
            "unknown": unknown,
        },
    )


def _load_token(ref):
    from vault import service as vault_service
    from vault.models import Secret

    secret = (
        Secret.objects.filter(
            kind=Secret.Kind.API_TOKEN,
            owner_type=OWNER_TYPE,
            owner_id=ref,
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if secret is None:
        raise TailscaleError("no api_token secret in the vault for the tailscale ref")
    raw = vault_service.get(secret, reason="tailscale device audit")
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    token = str(raw).strip()
    if not token:
        raise TailscaleError("refused: empty tailscale credential")
    return token


def _targets():
    from core.models import Target

    return list(Target.objects.all())


def _normalize(row):
    if not isinstance(row, dict):
        return {"id": "", "hostname": "", "name": "", "addresses": []}
    return {
        "id": str(row.get("id") or row.get("nodeId") or ""),
        "hostname": str(row.get("hostname") or ""),
        "name": str(row.get("name") or ""),
        "addresses": [str(addr) for addr in (row.get("addresses") or [])],
    }


def _device_id(device):
    return str(
        device.get("id") or device.get("nodeId") or device.get("hostname") or "",
    ).strip()


def _aliases(device):
    aliases = set()
    for key in ("hostname", "name", "id"):
        value = str(device.get(key) or "").strip().lower()
        if value:
            aliases.add(value)
    for addr in device.get("addresses") or ():
        value = str(addr or "").strip().lower()
        if value:
            aliases.add(value)
    return aliases


def _matches_hub_target(device, targets):
    aliases = _aliases(device)
    if not aliases:
        return False
    for target in targets:
        host = (target.host or "").strip().lower()
        if host and host in aliases:
            return True
    return False


def _file_unknown(device, device_id):
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    hostname = str(device.get("hostname") or "").strip() or device_id
    raise_alert(
        "tailscale-unknown-device",
        f"tailscale-device:{device_id}",
        workspace=default_workspace(),
        fingerprint=f"{ALERT_KIND}:{device_id}",
        source_engine=SOURCE_ENGINE,
        title=f"Unknown Tailscale device {hostname}",
        body=(
            f"Device {hostname} is on the tailnet but is not a Hub Target. "
            "A machine the Hub did not enroll can reach the mesh."
        ),
        fix_action=(
            "Remove the device from the tailnet or enroll it as a Hub Target"
        ),
    )
