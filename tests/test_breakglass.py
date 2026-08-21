"""Break-glass runbook on the target: mode 0400, no vault plaintext (P5 / VAL-45)."""
import pytest

from core.transport import FakeTransport

SECRET = "VAULT-TEST-PLAINTEXT-MARKER-do-not-log"
SLUG = "ops"


class ModeTransport(FakeTransport):
    """Captures put mode; FakeTransport.calls still store only the remote path."""

    def __init__(self):
        super().__init__()
        self.put_modes = {}

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        super().put(local_path_or_bytes, remote_path, mode=mode)
        self.put_modes[remote_path] = mode


def _text(payload):
    if isinstance(payload, (bytes, bytearray)):
        return payload.decode()
    return payload


def _desired(transport, *, extra=None):
    desired = {
        "transport": transport,
        "site_slug": SLUG,
        "deployment_id": 12,
        "manifest_body": {
            "domain": "ops.example.com",
            "env": {"DATABASE_URL": SECRET},
        },
        "domain": "ops.example.com",
        "old_container": f"site-{SLUG}-11",
        "env": {"DATABASE_URL": SECRET},
    }
    if extra:
        desired.update(extra)
    return desired


@pytest.mark.req("SEC-P5-BREAK-GLASS")
@pytest.mark.req("VAL-45-SHELL-ARGLISTS")
def test_runbook_mode_0400():
    """The runbook is delivered with put(..., mode=0o400), never a shell heredoc.

    What would make this fail: default 0o644, writing via run() with <<, or
    passing a shell string instead of putting bytes.
    """
    from deploys.breakglass import write_runbook

    transport = ModeTransport()
    write_runbook(_desired(transport))

    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts, "expected transport.put of the runbook"
    remote = puts[0]
    assert SLUG in remote
    assert transport.put_modes[remote] == 0o400
    text = _text(transport.files[remote])
    assert text.strip()
    assert "<<" not in " ".join(
        str(part) for kind, argv in transport.calls
        if kind == "run" and isinstance(argv, list)
        for part in argv
    )
    for kind, payload in transport.calls:
        if kind in {"run", "probe"}:
            assert isinstance(payload, list)


@pytest.mark.req("SEC-P5-BREAK-GLASS")
@pytest.mark.req("VAL-45-SHELL-ARGLISTS")
def test_runbook_contains_no_vault_plaintext():
    """Planted vault plaintext must not appear in the on-target markdown.

    What would make this fail: interpolating env values, dumping the vault
    marker, or embedding desired['env'] into the runbook body.
    """
    from deploys.breakglass import write_runbook

    transport = ModeTransport()
    write_runbook(_desired(transport))
    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts
    text = _text(transport.files[puts[0]])
    assert SECRET not in text
    assert SLUG in text or "ops.example.com" in text
