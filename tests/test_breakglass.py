"""Break-glass runbook on the target: mode 0400, no vault plaintext (P5 / VAL-45)."""
import pathlib
import re

import pytest

from core.transport import FakeTransport

SECRET = "VAULT-TEST-PLAINTEXT-MARKER-do-not-log"
TOKEN = "cf-dns-t1-planted-token-do-not-exfiltrate-bg16"
SLUG = "ops"
IMAGE = "registry.example.test/ops@sha256:cafebabefeed"
GENERATED_AT = "2026-08-22T15:14:00Z"
CERT_EXPIRY = "2028-03-01T00:00:00Z"
RECREATE_DOWN = "Site is down — old version is not serving"
BLUE_GREEN_SERVING = "Old version still serving — site unaffected"


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


def _written(*, extra=None):
    from deploys.breakglass import write_runbook

    transport = ModeTransport()
    defaults = {
        "step": "cutover",
        "strategy": "blue_green",
        "image_tag": IMAGE,
    }
    if extra:
        defaults.update(extra)
    write_runbook(_desired(transport, extra=defaults))
    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts, "expected transport.put of the runbook"
    remote = puts[0]
    return transport, remote, _text(transport.files[remote])


def _first_command_index(text):
    markers = ("## Restart", "## Rollback", "docker start", "docker stop")
    found = [text.find(m) for m in markers if m in text]
    assert found, f"no operator command section in:\n{text}"
    return min(found)


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

    What would make this fail: interpolating desired['env'] or
    manifest_body env values so the planted marker is rendered (the
    renderer must not strip that marker after the fact).
    """
    from deploys.breakglass import write_runbook

    transport = ModeTransport()
    write_runbook(_desired(transport))
    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts
    text = _text(transport.files[puts[0]])
    assert SECRET not in text
    assert SLUG in text or "ops.example.com" in text


@pytest.mark.req("SEC-P5-BREAK-GLASS")
def test_runbook_states_impact_before_commands():
    """Impact is the first thing an operator reads; commands come after.

    What would make this fail: omitting the §F4 line, putting docker/DNS
    commands above it, or literaling a second copy of the impact sentences
    in breakglass.py instead of calling impact_line().
    """
    from deploys.failure_impact import impact_line

    _, _, down = _written(extra={"step": "health_check", "strategy": "recreate"})
    assert RECREATE_DOWN == impact_line("health_check", "recreate")
    assert RECREATE_DOWN in down
    assert down.index(RECREATE_DOWN) < _first_command_index(down)

    _, _, serving = _written(extra={"step": "health_check", "strategy": "blue_green"})
    assert BLUE_GREEN_SERVING == impact_line("health_check", "blue_green")
    assert BLUE_GREEN_SERVING in serving
    assert serving.index(BLUE_GREEN_SERVING) < _first_command_index(serving)
    assert RECREATE_DOWN not in serving

    class _Step:
        name = "health_check"

    _, _, from_row = _written(extra={"step": _Step(), "strategy": "recreate"})
    assert RECREATE_DOWN in from_row

    src = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "deploys", "breakglass.py",
    ).read_text()
    leaked = [s for s in (RECREATE_DOWN, BLUE_GREEN_SERVING) if s in src]
    assert leaked == [], f"breakglass.py literals impact copy: {leaked}"


@pytest.mark.req("SEC-P5-BREAK-GLASS")
def test_dns_section_names_hub_side_commands_only():
    """DNS copy is Hub-side upsert_record; a target-side token command is SEC-B2.

    What would make this fail: leaving the Phase 2 comment stub, documenting
    curl/CF_API_TOKEN on the target, or omitting this site's upsert_record.
    """
    _, _, text = _written(extra={
        "step": "dns",
        "strategy": "blue_green",
        "dns_values": ["203.0.113.10"],
        "zone": "example.com",
        "dns_token": TOKEN,
    })
    assert "## DNS" in text
    dns_section = text.split("## DNS", 1)[1]
    lower = dns_section.lower()
    assert "hub-side" in lower or "hub side" in lower
    assert "upsert_record" in dns_section
    assert "ops.example.com" in dns_section
    assert "203.0.113.10" in dns_section
    assert TOKEN not in text
    assert "CF_API_TOKEN" not in dns_section
    assert "Authorization" not in dns_section
    assert "nsupdate" not in lower
    assert "curl" not in lower


@pytest.mark.req("SEC-P5-BREAK-GLASS")
def test_runbook_carries_generated_at_deployment_and_schema_version():
    """Freshness metadata so a stale file at 2 a.m. is visible as stale.

    What would make this fail: omitting generated-at, the deployment id,
    the image tag this file describes, or a runbook schema version.
    """
    _, _, text = _written(extra={
        "generated_at": GENERATED_AT,
        "cert_mode": "origin_cert",
        "cert_expiry": CERT_EXPIRY,
    })
    assert GENERATED_AT in text
    assert re.search(r"deployment(?:[_\s-]?id)?\s*[:=]\s*12", text, re.I)
    assert IMAGE in text
    assert re.search(r"schema[_\s-]*version\s*[:=]\s*\d+", text, re.I)
    assert "origin_cert" in text
    assert "2028-03-01" in text


@pytest.mark.req("SEC-P5-BREAK-GLASS")
def test_runbook_contains_no_token_and_no_secret():
    """Planted vault plaintext and a DNS token must not appear.

    What would make this fail: interpolating env, dns_token, key_ref, or
    a vault ref into the markdown.
    """
    _, _, text = _written(extra={
        "dns_token": TOKEN,
        "dns_token_ref": "vault-ref-dns-PLANTED",
        "key_ref": "site-99-tls",
        "env": {"DATABASE_URL": SECRET, "CF_API_TOKEN": TOKEN},
        "manifest_body": {
            "domain": "ops.example.com",
            "env": {"DATABASE_URL": SECRET, "CF_API_TOKEN": TOKEN},
        },
    })
    assert SECRET not in text
    assert TOKEN not in text
    assert "vault-ref-dns-PLANTED" not in text
    assert "CF_API_TOKEN" not in text
    assert SLUG in text or "ops.example.com" in text
    assert "upsert_record" in text
    assert "advisory only" in text.lower()


@pytest.mark.req("SEC-P5-BREAK-GLASS")
@pytest.mark.req("VAL-45-SHELL-ARGLISTS")
def test_runbook_is_0400_and_root_owned():
    """put(..., mode=0o400) then chown root:root; never a heredoc.

    What would make this fail: default 0o644, skipping chown, or writing
    via run() with <<.
    """
    transport, remote, text = _written()
    assert SLUG in remote
    assert transport.put_modes[remote] == 0o400
    assert text.strip()
    chowns = [
        argv for kind, argv in transport.calls
        if kind == "run" and isinstance(argv, list) and "chown" in argv
    ]
    assert chowns, "expected transport.run chown of the runbook"
    assert any("root:root" in argv for argv in chowns)
    assert "<<" not in " ".join(
        str(part) for kind, argv in transport.calls
        if kind == "run" and isinstance(argv, list)
        for part in argv
    )
    for kind, payload in transport.calls:
        if kind in {"run", "probe"}:
            assert isinstance(payload, list)


@pytest.mark.req("SEC-P5-BREAK-GLASS")
def test_advisory_only_note_present():
    """alert-protocol §3: pager-sourced commands are advisory only.

    What would make this fail: omitting the §M3 note, or wording that
    tells the operator to type a command whose only provenance is a push.
    """
    _, _, text = _written()
    lower = text.lower()
    assert "advisory only" in lower
    assert "findings inbox" in lower
