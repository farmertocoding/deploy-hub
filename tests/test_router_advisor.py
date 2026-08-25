"""Phase 7.1 tunnel probe: nothing forwarded (C1–C4, C7).

probe_nothing_forwarded files router-forwarded:{pk} when an injected
wan_probe reports any WAN map, and resolves that fingerprint when forwards
is empty. HTTP lives in monitor/router_views.py. Default wan_probe is
refuse-closed — tests inject by wrapping the view's callee.
"""
import ast
import inspect
import json
import pathlib
import re

import pytest

from core.models import Finding, NetworkZone, Target

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
PROBE = "/api/v1/targets/{pk}/router-probe/"
DETAIL = "/api/v1/targets/{pk}/"
LIST = "/api/v1/targets/"
INSTANCE_WORD = re.compile(r"\binstance\b")
TITLE = "Tunnel target has a WAN forward"
FIX = "Remove the WAN port mapping on the router, then Probe router."
BANNED_IMPORTS = frozenset({"deploys", "providers", "vault"})
BANNED_SOURCE = (
    "subprocess", "socket.create_connection", "upnp", "ssdp", "minissdp",
)
ADVISOR = REPO / "monitor" / "router_advisor.py"
VIEWS = REPO / "monitor" / "router_views.py"


def _zone(slug="router-lan"):
    return NetworkZone.objects.create(name=slug, slug=slug)


def _target(zone, host, *, kind="ssh", tunnel=None):
    kwargs = {
        "zone": zone,
        "host": host,
        "kind": kind,
        "status": Target.Status.READY,
    }
    if tunnel is True:
        kwargs["collect_payload"] = {"tunnel": True}
    elif tunnel is False:
        kwargs["collect_payload"] = {"tunnel": False}
    return Target.objects.create(**kwargs)


def _forwards(*rows):
    def wan_probe():
        return {"forwards": [dict(row) for row in rows]}

    return wan_probe


def _login(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.login(username="joseph", password="a-long-dev-password")
    return user


def _inject_wan(monkeypatch, forwards):
    """Wrap the view callee so HTTP never binds a WAN scan from the body."""
    from monitor import router_advisor as advisor

    real = advisor.probe_nothing_forwarded

    def injected():
        return {"forwards": [dict(row) for row in forwards]}

    def wrapped(target, *, wan_probe=None):
        return real(target, wan_probe=wan_probe or injected)

    monkeypatch.setattr("monitor.router_views.probe_nothing_forwarded", wrapped)
    return injected


def _post_probe(client, target, body=None):
    kwargs = {"content_type": "application/json"}
    if body is not None:
        kwargs["data"] = json.dumps(body)
    return client.post(PROBE.format(pk=target.pk), **kwargs)


def _copy_ok(row):
    assert row.title.strip(), "§6.6 title (what) is blank"
    assert row.body.strip(), "§6.6 body (why it matters) is blank"
    assert row.fix_action.strip(), "§6.6 fix_action (exact fix) is blank"
    assert INSTANCE_WORD.search(row.title) is None
    assert INSTANCE_WORD.search(row.body) is None
    assert INSTANCE_WORD.search(row.fix_action) is None


@pytest.mark.req("ROUTER-TUNNEL-NOTHING-FORWARDED")
def test_tunnel_forward_files_finding():
    """A tunnel target with any WAN forward files router-forwarded:{pk}.

    What would make this fail: skipping tunnel targets, filing a second
    fingerprint, or copy that omits the port/proto / Cloudflare Tunnel why.
    """
    from monitor.router_advisor import probe_nothing_forwarded

    box = _target(_zone(), "tun.lan", kind="ssh", tunnel=True)
    result = probe_nothing_forwarded(
        box, wan_probe=_forwards({"port": 443, "proto": "tcp"}),
    )

    fp = f"router-forwarded:{box.pk}"
    row = Finding.objects.get(fingerprint=fp)
    assert row.source_engine == "router_advisor"
    assert row.severity == Finding.Severity.P2
    assert row.entity == f"target:{box.pk}"
    assert row.state == Finding.State.OPEN
    assert row.title == TITLE
    assert row.fix_action == FIX
    assert "443" in row.body
    assert "tcp" in row.body
    assert "Cloudflare Tunnel" in row.body
    assert "bypass" in row.body.lower()
    _copy_ok(row)
    assert result["mode"] == "tunnel"
    assert result["finding_id"] == row.pk


@pytest.mark.req("ROUTER-TUNNEL-NOTHING-FORWARDED")
def test_empty_forwards_resolves_finding():
    """Empty forwards resolve OPEN/ACKED; ACCEPTED stays one row.

    What would make this fail: leaving OPEN after a clean probe, resolving
    ACCEPTED, or filing a second row for the same fingerprint.
    """
    from core.findings import accept_risk
    from monitor.router_advisor import probe_nothing_forwarded

    zone = _zone("router-empty")
    box = _target(zone, "tun-empty.lan", kind="ssh", tunnel=True)
    probe_nothing_forwarded(
        box, wan_probe=_forwards({"port": 80, "proto": "udp"}),
    )
    fp = f"router-forwarded:{box.pk}"
    row = Finding.objects.get(fingerprint=fp)
    assert row.state == Finding.State.OPEN

    result = probe_nothing_forwarded(box, wan_probe=_forwards())
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert result["finding_id"] is None
    assert Finding.objects.filter(fingerprint=fp).count() == 1

    other = _target(zone, "tun-acked.lan", kind="ssh", tunnel=True)
    probe_nothing_forwarded(
        other, wan_probe=_forwards({"port": 22, "proto": "tcp"}),
    )
    acked = Finding.objects.get(fingerprint=f"router-forwarded:{other.pk}")
    acked.state = Finding.State.ACKED
    acked.save(update_fields=["state"])
    probe_nothing_forwarded(other, wan_probe=_forwards())
    acked.refresh_from_db()
    assert acked.state == Finding.State.RESOLVED

    kept = _target(zone, "tun-accepted.lan", kind="ssh", tunnel=True)
    probe_nothing_forwarded(
        kept, wan_probe=_forwards({"port": 443, "proto": "tcp"}),
    )
    accepted = Finding.objects.get(fingerprint=f"router-forwarded:{kept.pk}")
    accept_risk(accepted, "lab forwards 443 on purpose")
    accepted.refresh_from_db()
    assert accepted.state == Finding.State.ACCEPTED
    probe_nothing_forwarded(kept, wan_probe=_forwards())
    accepted.refresh_from_db()
    assert accepted.state == Finding.State.ACCEPTED
    assert Finding.objects.filter(
        fingerprint=f"router-forwarded:{kept.pk}",
    ).count() == 1


@pytest.mark.req("ROUTER-TUNNEL-NOTHING-FORWARDED")
def test_missing_wan_probe_does_not_file():
    """Default wan_probe is refuse-closed — missing inject must not file.

    What would make this fail: treating None as empty-forwards (false
    resolve) or as a live scan (false alarm).
    """
    from monitor.router_advisor import probe_nothing_forwarded

    box = _target(_zone("router-noseam"), "tun-noseam.lan", tunnel=True)
    result = probe_nothing_forwarded(box)
    assert result["mode"] == "no_seam"
    assert Finding.objects.filter(
        fingerprint=f"router-forwarded:{box.pk}",
    ).count() == 0
    assert result.get("finding_id") in (None, 0)


@pytest.mark.req("ROUTER-TUNNEL-NOTHING-FORWARDED")
def test_non_tunnel_skips():
    """Non-tunnel targets skip even when a probe would report forwards.

    What would make this fail: filing on collect_payload.tunnel is False
    or missing, so POST could not 4xx `not tunnel mode`.
    """
    from monitor.router_advisor import probe_nothing_forwarded

    zone = _zone("router-nontun")
    plain = _target(zone, "plain.lan", kind="ssh")
    flagged = _target(zone, "flagged.lan", kind="ssh", tunnel=False)
    for box in (plain, flagged):
        result = probe_nothing_forwarded(
            box, wan_probe=_forwards({"port": 443, "proto": "tcp"}),
        )
        assert result["mode"] == "not_tunnel"
        assert Finding.objects.filter(
            fingerprint=f"router-forwarded:{box.pk}",
        ).count() == 0


@pytest.mark.req("ROUTER-TUNNEL-NOTHING-FORWARDED")
def test_module_has_no_live_wan_scan():
    """C7: advisor/views must not scan WAN, import deploys/providers/vault.

    What would make this fail: subprocess, socket.create_connection, or
    UPnP/SSDP in the new modules.
    """
    for path in (ADVISOR, VIEWS):
        src = path.read_text(encoding="utf-8")
        lowered = src.lower()
        for token in BANNED_SOURCE:
            assert token not in lowered, f"{path.name} contains {token}"
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported.isdisjoint(BANNED_IMPORTS), imported & BANNED_IMPORTS
        assert "subprocess" not in imported
        assert INSTANCE_WORD.search(src) is None, path.name


@pytest.mark.req("ROUTER-ADVICE-TARGET-TAB")
def test_target_detail_returns_router_advice(client):
    """GET detail adds router_advice; list carries {id, host, kind, tunnel}.

    What would make this fail: omitting mode/finding_id, or listing a
    tunnel target as tunnel=false.
    """
    from monitor.router_advisor import probe_nothing_forwarded

    zone = _zone("router-http")
    box = _target(zone, "tun-http.lan", kind="ssh", tunnel=True)
    plain = _target(zone, "plain-http.lan", kind="ssh", tunnel=False)
    probe_nothing_forwarded(
        box, wan_probe=_forwards({"port": 443, "proto": "tcp"}),
    )
    row = Finding.objects.get(fingerprint=f"router-forwarded:{box.pk}")
    _login(client)

    listed = client.get(LIST)
    assert listed.status_code == 200, listed.content
    by_id = {item["id"]: item for item in listed.json()}
    assert set(by_id[box.pk]) >= {"id", "host", "kind", "tunnel"}
    assert by_id[box.pk]["host"] == "tun-http.lan"
    assert by_id[box.pk]["kind"] == "ssh"
    assert by_id[box.pk]["tunnel"] is True
    assert by_id[plain.pk]["tunnel"] is False

    detail = client.get(DETAIL.format(pk=box.pk))
    assert detail.status_code == 200, detail.content
    body = detail.json()
    advice = body["router_advice"]
    assert advice["mode"] == "tunnel"
    assert advice["forwarded"]
    assert advice["finding_id"] == row.pk
    assert advice["title"] == TITLE
    assert "443" in advice["body"]
    assert "Cloudflare Tunnel" in advice["body"]

    plain_detail = client.get(DETAIL.format(pk=plain.pk)).json()
    assert plain_detail["router_advice"]["mode"] == "not_tunnel"
    assert plain_detail["router_advice"]["finding_id"] is None


@pytest.mark.req("ROUTER-ADVICE-TARGET-TAB")
def test_probe_http_t3_empty_forwards_resolves(client, monkeypatch):
    """POST T3 Probe router with empty forwards resolves the OPEN row.

    What would make this fail: a confirm/step-up row, a non-empty
    serializer, or 201 that leaves the finding OPEN.
    """
    from core.actions import ACTION_TIERS
    from monitor.router_advisor import probe_nothing_forwarded
    from monitor.router_views import RouterProbeSerializer, RouterProbeView

    box = _target(_zone("router-t3"), "tun-t3.lan", kind="ssh", tunnel=True)
    probe_nothing_forwarded(
        box, wan_probe=_forwards({"port": 443, "proto": "tcp"}),
    )
    row = Finding.objects.get(fingerprint=f"router-forwarded:{box.pk}")
    assert row.state == Finding.State.OPEN

    action = next(r for r in ACTION_TIERS if r["id"] == "target.router_probe")
    assert action == {
        "id": "target.router_probe",
        "tier": "T3",
        "label": "Probe router",
        "undo_window_s": 10,
    }
    assert RouterProbeSerializer().get_fields() == {}
    source = inspect.getsource(RouterProbeView)
    assert "wan_probe=" in source
    assert "request.data.get" not in source
    assert "request.data[" not in source

    _inject_wan(monkeypatch, [])
    _login(client)
    response = _post_probe(client, box)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["ok"] is True
    assert body["target_id"] == box.pk
    assert not body["forwarded"]
    assert body["finding_id"] is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED

    detail = client.get(DETAIL.format(pk=box.pk)).json()
    assert detail["router_advice"]["finding_id"] is None


@pytest.mark.req("ROUTER-ADVICE-TARGET-TAB")
def test_probe_http_missing_inject_is_4xx(client):
    """POST without wan_probe inject is 4xx `wan probe refused`, no Finding.

    What would make this fail: binding forwards from the request body, or
    filing when the seam is missing.
    """
    box = _target(_zone("router-refuse"), "tun-refuse.lan", tunnel=True)
    _login(client)
    before = Finding.objects.count()
    response = _post_probe(client, box)
    assert 400 <= response.status_code < 500, response.content
    blob = response.content.decode()
    assert "wan probe refused" in blob
    assert Finding.objects.count() == before
    sneaky = _post_probe(
        client, box,
        body={"forwards": [{"port": 443, "proto": "tcp"}], "wan_probe": True},
    )
    assert 400 <= sneaky.status_code < 500, sneaky.content
    assert "wan probe refused" in sneaky.content.decode()
    assert Finding.objects.filter(
        fingerprint=f"router-forwarded:{box.pk}",
    ).count() == 0


@pytest.mark.req("ROUTER-ADVICE-TARGET-TAB")
def test_probe_http_non_tunnel_is_4xx(client, monkeypatch):
    """POST on a non-tunnel target is 4xx `not tunnel mode`.

    What would make this fail: running the probe anyway, or a 2xx that
    files nothing so the client thinks the router is clean.
    """
    box = _target(_zone("router-skip"), "plain-skip.lan", tunnel=False)
    _inject_wan(monkeypatch, [{"port": 443, "proto": "tcp"}])
    _login(client)
    response = _post_probe(client, box)
    assert 400 <= response.status_code < 500, response.content
    assert "not tunnel mode" in response.content.decode()
    assert Finding.objects.filter(
        fingerprint=f"router-forwarded:{box.pk}",
    ).count() == 0
