"""ensure_route_tls: Caddy PUT-by-id via argv lists; second call is a skip (D6 / VAL-45)."""
import json

import pytest

from core.transport import CommandResult, FakeTransport

SLUG = "blog"
ROUTE_ID = f"site-{SLUG}"
ADMIN = f"http://127.0.0.1:2019/id/{ROUTE_ID}"


class RouteTransport(FakeTransport):
    """Remembers the last PUT body so a second ensure can probe and skip."""

    def __init__(self):
        super().__init__()
        self.routes = {}
        self.put_modes = {}

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        super().put(local_path_or_bytes, remote_path, mode=mode)
        self.put_modes[remote_path] = mode

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        route_id = _route_id_from_argv(argv)
        if argv and argv[0] == "curl" and "PUT" not in argv and route_id:
            raw = self.routes.get(route_id)
            if raw is None:
                return CommandResult(argv, exit_code=1, stderr="404")
            stdout = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            return CommandResult(argv, stdout=stdout)
        return CommandResult(argv)

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        route_id = _route_id_from_argv(argv)
        if argv and argv[0] == "curl" and "PUT" in argv and route_id:
            path = _data_binary_path(argv)
            raw = self.files.get(path, b"{}")
            self.routes[route_id] = raw
        return result


def _route_id_from_argv(argv):
    for part in argv:
        text = str(part)
        if "/id/" in text or "/servers/" in text:
            return text.rstrip("/").rsplit("/", 1)[-1]
    return None


def _data_binary_path(argv):
    if "--data-binary" in argv:
        spec = argv[argv.index("--data-binary") + 1]
        return spec[1:] if spec.startswith("@") else spec
    for part in argv:
        if isinstance(part, str) and part.startswith("@") and not part.startswith("--"):
            return part[1:]
    return None


def _upstream_dials(route):
    dials = []
    for item in route.get("routes") or []:
        for handle in item.get("handle") or []:
            for upstream in handle.get("upstreams") or []:
                if upstream.get("dial"):
                    dials.append(upstream["dial"])
    return dials


def _put_json(transport):
    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts, "expected put of Caddy route JSON"
    for remote in puts:
        raw = transport.files.get(remote)
        if raw is None:
            continue
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        try:
            data = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("@id"):
            return data
    raise AssertionError("expected put of Caddy route JSON with @id")


def _mutating_runs(transport):
    return [argv for kind, argv in transport.mutating_calls() if kind == "run"]


def _desired(transport, *, exposure="public", mesh_bind=None, domain="blog.example.com"):
    body = {"exposure": exposure, "domain": domain}
    if mesh_bind is not None:
        body["mesh_bind"] = mesh_bind
    return {
        "transport": transport,
        "site_slug": SLUG,
        "deployment_id": 8,
        "manifest_body": body,
        "domain": domain,
    }


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.req("VAL-45-SHELL-ARGLISTS")
def test_caddy_put_by_id():
    """Route JSON is put, then applied with a curl/caddy argv list keyed site-{slug}.

    What would make this fail: missing @id site-{slug}, listen not mesh-bind vs
    :443, a hardcoded upstream, applying via a shell string or heredoc, or
    shipping a Cloudflare origin certificate this phase.
    """
    from deploys.steps import ensure_route_tls

    transport = RouteTransport()
    desired = _desired(transport, exposure="public")
    desired["internal_port"] = 21000
    ensure_route_tls(desired)

    route = _put_json(transport)
    assert route["@id"] == ROUTE_ID
    assert route.get("listen") == [":443"]
    assert route.get("tls_connection_policies") == [{
        "certificate_selection": {"any_tag": [ROUTE_ID]},
    }]
    dumped = json.dumps(route)
    assert "BEGIN CERTIFICATE" not in dumped
    assert "-----BEGIN" not in dumped
    assert _upstream_dials(route) == ["127.0.0.1:21000"]
    tls_puts = [
        argv for argv in _mutating_runs(transport)
        if any("/config/apps/tls" in str(part) for part in argv)
    ]
    assert tls_puts, "expected a load_files PUT of the pushed cert/key paths"
    tls_blob = None
    for remote, raw in transport.files.items():
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        if isinstance(text, str) and "load_files" in text:
            tls_blob = text
            break
    assert tls_blob is not None
    assert "/srv/sites/blog/tls/cert.pem" in tls_blob
    assert "/srv/sites/blog/tls/key.pem" in tls_blob
    assert "BEGIN" not in tls_blob

    runs = _mutating_runs(transport)
    assert runs, "expected a curl/caddy run after put"
    assert all(isinstance(argv, list) for argv in runs)
    assert all(not isinstance(argv, str) for argv in runs)
    assert any(argv and argv[0] in {"curl", "caddy"} for argv in runs)
    assert any(any(ROUTE_ID in str(part) or ADMIN in str(part) for part in argv)
               for argv in runs)
    joined = " ".join(str(part) for argv in runs for part in argv)
    assert "<<" not in joined
    assert "heredoc" not in joined.lower()

    mesh = RouteTransport()
    ensure_route_tls(_desired(mesh, exposure="mesh_only", mesh_bind="100.64.1.8"))
    mesh_route = _put_json(mesh)
    assert mesh_route["@id"] == ROUTE_ID
    assert mesh_route.get("listen") == ["100.64.1.8:443"]
    assert ":443" not in mesh_route["listen"]
    assert "tls_connection_policies" not in mesh_route
    mesh_runs = _mutating_runs(mesh)
    assert not any(
        "/config/apps/tls" in str(part) for argv in mesh_runs for part in argv
    )


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_route_zero_mutating_calls():
    """An identical Caddy route is probed and skipped; the second call does not put.

    What would make this fail: put/run on the second call, or inspecting the
    current route via run so mutating_calls is never empty.
    """
    from deploys.steps import ensure_route_tls

    transport = RouteTransport()
    desired = _desired(transport)
    ensure_route_tls(desired)
    assert transport.mutating_calls(), "first call must put/run so the second can skip"
    assert ROUTE_ID in transport.routes

    transport.calls.clear()
    ensure_route_tls(desired)
    assert transport.mutating_calls() == []
    probes = [(kind, argv) for kind, argv in transport.calls if kind == "probe"]
    assert probes
    assert all(kind == "probe" for kind, argv in probes)


@pytest.mark.req("REL-P4-ARTIFACT-SNAPSHOTS")
def test_overlay_caddy_route_is_put_not_derived():
    """desired['caddy_route'] is PUT even when it differs from _caddy_route(body).

    What would make this fail: ensure_route_tls re-deriving listen/upstreams from
    the current body and ignoring the overlay JSON.
    """
    from deploys.steps import _caddy_route, ensure_route_tls

    transport = RouteTransport()
    desired = _desired(transport)
    derived = _caddy_route(desired, ROUTE_ID)
    overlay = dict(derived)
    overlay["listen"] = ["127.0.0.1:9999"]
    desired["caddy_route"] = json.dumps(
        overlay, sort_keys=True, separators=(",", ":"),
    )
    assert overlay != derived

    ensure_route_tls(desired)
    put = _put_json(transport)
    assert put["listen"] == ["127.0.0.1:9999"]
    assert put["listen"] != derived.get("listen")
