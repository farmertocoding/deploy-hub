"""Quarterly SSH rotation: dual-key overlap, probe-before-revoke (D-064 / C8).

Generate Ed25519 in-Hub, append the pubkey, Transport.probe login with the
new key, only then drop the old pubkey, point Target.ssh_key_ref, probe old
fails / new works, revoke the old Secret. Never ssh-keygen on the target.
Never clobber authorized_keys with a single-key install during overlap.
Private key material stays in the vault. Overlap itself is not a Finding.
"""
import copy
import secrets
from datetime import timedelta

from vault import service as vault_service
from vault.models import Secret

QUARTER = timedelta(days=90)
LOGIN_ARGV = ["true"]
SOURCE = "ssh_rotate"
RESULTS_SCHEMA_VERSION = 1
COMMENT_PREFIX = "hub-ssh:"


def authorized_keys_path(target):
    user = target.ssh_user or "root"
    if user == "root":
        return "/root/.ssh/authorized_keys"
    return f"/home/{user}/.ssh/authorized_keys"


def _blob(line):
    parts = (line or "").split()
    return parts[1] if len(parts) >= 2 else ""


def _comment(owner_id):
    return f"{COMMENT_PREFIX}{owner_id}"


def _public_line_from_pem(pem, comment=""):
    from vault.ssh import public_openssh_from_pem

    pub = public_openssh_from_pem(pem)
    if comment:
        return f"{pub} {comment}"
    return pub


def _generate_ed25519():
    """In-Hub keygen. The private key is vaulted; only the pubkey is shipped."""
    from vault.ssh import generate_ed25519_keypair

    return generate_ed25519_keypair()


def _current_secret(target):
    if not target.ssh_key_ref:
        return None
    return (
        Secret.objects.filter(
            kind=Secret.Kind.SSH_PRIVATE_KEY,
            owner_id=target.ssh_key_ref,
        )
        .order_by("-created_at")
        .first()
    )


def _pending_secrets(target):
    """Newer-than-current prefix rows: resume incomplete, never a kept stale old."""
    prefix = f"target-{target.pk}-ssh-"
    qs = Secret.objects.filter(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id__startswith=prefix,
    )
    if target.ssh_key_ref:
        qs = qs.exclude(owner_id=target.ssh_key_ref)
    rows = list(qs.order_by("-created_at"))
    current = _current_secret(target)
    if current is None or current.created_at is None:
        return rows
    return [row for row in rows if row.created_at > current.created_at]


def _inspect(transport, path):
    """Read authorized_keys. Non-ok cat is not an empty file (D-064)."""
    result = transport.probe(["cat", path])
    text = result.stdout or ""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode(errors="replace")
    if not result.ok:
        return None
    return text


def _put_keys(transport, path, text):
    if text and not text.endswith("\n"):
        text += "\n"
    transport.put(text.encode(), path, mode=0o600)


def _append_line(text, line):
    line = line if line.endswith("\n") else f"{line}\n"
    blob = _blob(line)
    for existing in text.splitlines():
        if _blob(existing) == blob:
            return text, False
    if text and not text.endswith("\n"):
        text += "\n"
    return text + line, True


def _drop_blob(text, blob):
    kept = []
    changed = False
    for existing in text.splitlines():
        if existing.strip() and _blob(existing) == blob:
            changed = True
            continue
        kept.append(existing)
    if not kept:
        return ("", changed)
    return "\n".join(kept) + "\n", changed


def _login(make_transport, target, key_ref):
    from core.ssh import HostKeyMismatch

    probe_target = copy.copy(target)
    probe_target.ssh_key_ref = key_ref
    try:
        result = make_transport(probe_target).probe(list(LOGIN_ARGV))
    except HostKeyMismatch:
        raise
    except Exception:
        return False
    return bool(result.ok)


def _incomplete(target, why):
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    return raise_alert(
        "ssh-rotation-incomplete",
        f"target:{target.pk}",
        workspace=default_workspace(),
        fingerprint=f"ssh-rotation-incomplete:{target.pk}",
        source_engine=SOURCE,
        title="SSH key rotation incomplete",
        body=(
            f"Rotation of {target.host} stopped before the new key was confirmed "
            f"({why}). The previous key is still the login path. Dual-key overlap "
            "is intentional so this host is not locked out."
        ),
        fix_action="Re-run ssh.rotate on this target; do not edit authorized_keys by hand.",
    )


def _stale(target, why):
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    return raise_alert(
        "ssh-rotation-stale-key",
        f"target:{target.pk}",
        workspace=default_workspace(),
        fingerprint=f"ssh-rotation-stale-key:{target.pk}",
        source_engine=SOURCE,
        title="Stale SSH key after rotation",
        body=(
            f"Rotation of {target.host} intended to revoke the old key, but it "
            f"still authenticates ({why})."
        ),
        fix_action="Remove the old pubkey from this target's authorized_keys.",
    )


def _revoke(secret):
    from core.audit import audit

    audit(
        "vault-secret-revoked",
        secret,
        source="system",
        kind=secret.kind,
        owner_type=secret.owner_type,
        owner_id=secret.owner_id,
        fingerprint=secret.fingerprint,
    )
    pk = secret.pk
    secret.delete()
    return not Secret.objects.filter(pk=pk).exists()


def _store_new(target, pem):
    owner_id = f"target-{target.pk}-ssh-{secrets.token_hex(8)}"
    secret = vault_service.put(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id=owner_id,
        plaintext=pem,
    )
    return secret, owner_id


def _pem_and_pub(secret):
    pem = vault_service.get(secret, reason="ssh-rotate")
    return pem, _public_line_from_pem(pem, _comment(secret.owner_id))


def _extra_hub_lines(text, current_ref):
    marker = _comment(current_ref) if current_ref else None
    extra = []
    for line in text.splitlines():
        if COMMENT_PREFIX not in line:
            continue
        if marker is not None and marker in line:
            continue
        extra.append(line)
    return extra


def rotate_ssh(target, transport, *, make_transport=None, now=None, force=False):
    """Run (or resume) dual-key rotation for one Target. Second pass is inspect-only."""
    from django.utils import timezone

    from core.ssh import HostKeyMismatch, SshTransport

    make_transport = make_transport or SshTransport
    now = now or timezone.now()
    path = authorized_keys_path(target)
    text = _inspect(transport, path)
    if text is None:
        _incomplete(target, "could not read authorized_keys")
        return {"status": "incomplete", "new_ref": target.ssh_key_ref}
    current = _current_secret(target)
    pending = _pending_secrets(target)

    if (
        current is not None
        and not force
        and not pending
        and (now - current.created_at) < QUARTER
    ):
        extra = _extra_hub_lines(text, target.ssh_key_ref)
        _login(make_transport, target, target.ssh_key_ref)
        if extra:
            _stale(target, "old hub pubkey still in authorized_keys")
            return {"status": "stale", "new_ref": target.ssh_key_ref}
        return {"status": "skipped", "new_ref": target.ssh_key_ref}

    if pending:
        new_secret = pending[0]
        new_ref = new_secret.owner_id
        _, new_line = _pem_and_pub(new_secret)
    else:
        pem, pub = _generate_ed25519()
        new_secret, new_ref = _store_new(target, pem)
        new_line = f"{pub} {_comment(new_ref)}"

    new_text, appended = _append_line(text, new_line)
    if appended:
        _put_keys(transport, path, new_text)
        text = new_text

    try:
        new_ok = _login(make_transport, target, new_ref)
    except HostKeyMismatch:
        _incomplete(target, "host-key mismatch probing the new key")
        return {"status": "incomplete", "new_ref": new_ref}
    if not new_ok:
        _incomplete(target, "new key login probe failed")
        return {"status": "incomplete", "new_ref": new_ref}

    current_blob = _blob(_pem_and_pub(current)[1]) if current is not None else ""
    if current_blob:
        dropped, changed = _drop_blob(text, current_blob)
        if changed:
            _put_keys(transport, path, dropped)
            text = dropped

    if target.ssh_key_ref != new_ref:
        target.ssh_key_ref = new_ref
        target.save(update_fields=["ssh_key_ref"])

    old_still = False
    if current is not None and current_blob:
        old_login = _login(make_transport, target, current.owner_id)
        inspect_after = _inspect(transport, path)
        if inspect_after is None:
            _incomplete(target, "could not re-read authorized_keys after drop")
            return {"status": "incomplete", "new_ref": new_ref,
                    "old_ref": current.owner_id}
        if old_login or current_blob in inspect_after:
            old_still = True
            _stale(target, "old pubkey still present or still authenticates")

    try:
        new_ok_after = _login(make_transport, target, new_ref)
    except HostKeyMismatch:
        _incomplete(target, "host-key mismatch probing the new key after drop")
        return {"status": "incomplete", "new_ref": new_ref}
    if not new_ok_after:
        _incomplete(target, "new key failed after drop")
        return {"status": "incomplete", "new_ref": new_ref}

    if current is not None and not old_still:
        _revoke(current)

    return {
        "status": "stale" if old_still else "rotated",
        "new_ref": new_ref,
        "old_ref": current.owner_id if current is not None else "",
    }


def rotate_all(*, transport_for=None, force=False, now=None):
    """Beat body: rotate every READY SSH target; one CheckRun for the sweep."""
    from core.models import CheckRun, Target
    from core.ssh import SshTransport
    from monitor.drills import record_run

    factory = transport_for or SshTransport
    rotated, skipped, failed = [], [], []
    for target in Target.objects.filter(
        kind=Target.Kind.SSH, status=Target.Status.READY,
    ):
        transport = factory(target)
        result = rotate_ssh(
            target, transport, make_transport=factory, force=force, now=now,
        )
        status = result.get("status")
        if status == "rotated":
            rotated.append(target.pk)
        elif status in {"skipped", "stale"}:
            skipped.append(target.pk)
        else:
            failed.append(target.pk)
    overall = (
        CheckRun.Status.FAILED if failed else CheckRun.Status.SUCCEEDED
    )
    return record_run(
        CheckRun.Kind.SSH_ROTATE,
        overall,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "rotated": rotated,
            "skipped": skipped,
            "failed": failed,
        },
    )
