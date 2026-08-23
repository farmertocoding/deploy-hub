"""T1 Fake Partner Intake process: stdlib WSGI, six K3 routes, fail-closed verify.

This file must not import boto3/moto. T1 tests may import intake.
"""
import base64
import hashlib
import io
import json
import pathlib
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.urls import get_resolver

REPO = pathlib.Path(__file__).resolve().parent.parent
KEY_ID = "hubk_test_fixture"

# Design-note §7 C3 public families (two DELETE paths are one family).
K3_ROUTES = (
    ("POST", "/partner/v1/sites"),
    ("POST", "/partner/v1/sites/site_x/deployments"),
    ("GET", "/partner/v1/deployments/dep_x"),
    ("POST", "/partner/v1/sites/site_x/domains"),
    ("GET", "/partner/v1/domains/example.test"),
    ("DELETE", "/partner/v1/sites/site_x"),
    ("DELETE", "/partner/v1/sites/site_x/domains/example.test"),
)
NOT_PUBLIC = (
    ("GET", "/internal/outbox"),
    ("POST", "/internal/ack"),
    ("GET", "/internal/outbox/"),
    ("POST", "/internal/ack/"),
    ("POST", "/mcp"),
    ("GET", "/mcp"),
    ("POST", "/mcp/"),
    ("GET", "/api/partner"),
    ("POST", "/api/partner/v1/sites"),
    ("POST", "/partner/v1/webhooks"),
    ("POST", "/hooks/github"),
    ("GET", "/partner/v1/sites"),
    ("POST", "/partner/v1/git-push"),
    ("POST", "/partner/v2/sites"),
    ("POST", "/webhooks/github"),
    ("POST", "/hooks/gitea"),
    ("POST", "/api/github/webhook"),
    ("GET", "/hooks/github"),
)
HUB_CANDIDATE_PATHS = (
    "/api/partner",
    "/api/partner/",
    "/api/partner/v1/sites",
    "/partner/v1/sites",
    "/mcp",
    "/mcp/",
)


def _canonical(method, path, body, timestamp, nonce):
    digest = hashlib.sha256(body).hexdigest()
    return f"{method}\n{path}\n{digest}\n{timestamp}\n{nonce}"


def _sign(private_key, method, path, body=b""):
    timestamp = str(int(time.time()))
    nonce = hashlib.sha256(f"{timestamp}:{path}".encode()).hexdigest()[:32]
    message = _canonical(method, path, body, timestamp, nonce).encode("ascii")
    signature = base64.b64encode(private_key.sign(message)).decode("ascii")
    return {
        "X-Partner-Timestamp": timestamp,
        "X-Partner-Nonce": nonce,
        "X-Partner-Key-Id": KEY_ID,
        "X-Partner-Signature": signature,
    }


def _call(app, method, path, body=b"", headers=None):
    if isinstance(body, dict):
        body = json.dumps(body, separators=(",", ":")).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "intake.test",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(response_headers)
        return lambda chunk: None

    raw = b"".join(app(environ, start_response))
    code = int(captured["status"].split()[0])
    return code, captured.get("headers", {}), raw


def _fresh():
    from intake.app import make_application
    from intake.fake import FakeIntake

    fake = FakeIntake()
    private = Ed25519PrivateKey.generate()
    fake.register_public_key(KEY_ID, private.public_key())
    return make_application(fake), fake, private


def _route_strings(patterns=None, prefix=""):
    if patterns is None:
        patterns = get_resolver().url_patterns
    found = []
    for pattern in patterns:
        inner = pattern.pattern
        piece = getattr(inner, "_route", None)
        if piece is None:
            piece = str(inner)
        route = f"{prefix}{piece}"
        name = getattr(pattern, "name", None) or ""
        found.append(f"{route} {name}".lower())
        nested = getattr(pattern, "url_patterns", None)
        if nested is not None:
            found.extend(_route_strings(nested, route))
    return found


@pytest.mark.req("PART-INTAKE-PROCESS")
def test_intake_not_in_installed_apps():
    """intake/** is a separate process, never a Django app.

    What would make this fail: adding `"intake"` (or IntakeConfig) to
    INSTALLED_APPS, or never creating the intake/ tree.
    """
    assert (REPO / "intake").is_dir(), "intake/ process tree is missing"
    installed = list(settings.INSTALLED_APPS)
    assert "intake" not in installed
    assert not any(item == "intake" or str(item).startswith("intake.")
                   for item in installed)


def test_intake_is_not_a_django_app():
    """No AppConfig, models, or Django/Flask/FastAPI WSGI wrapper.

    What would make this fail: apps.py / models.py / get_wsgi_application /
    Flask() so the intake process is secretly a web framework.
    """
    root = REPO / "intake"
    assert root.is_dir(), "intake/ process tree is missing"
    for banned in ("apps.py", "models.py", "admin.py"):
        assert not (root / banned).exists(), banned
    assert not (root / "migrations").exists()
    app_src = (root / "app.py").read_text(encoding="utf-8")
    assert "get_wsgi_application" not in app_src
    assert "Flask" not in app_src
    assert "FastAPI" not in app_src
    assert "Starlette" not in app_src
    assert "django" not in app_src
    fake_src = (root / "fake.py").read_text(encoding="utf-8")
    for banned in ("HUB_WEBHOOK_SECRET", "GITHUB_WEBHOOK", "HUB_INTAKE_HMAC", "whsec_"):
        assert banned not in fake_src
        assert banned not in app_src


@pytest.mark.req("PART-K3-ENDPOINTS")
def test_public_listener_is_six_k3_routes_only():
    """Public WSGI listener is the six K3 families; git-push and mesh are not.

    What would make this fail: mounting /internal/outbox, /mcp, or a 7th
    public family on `application`, or 404ing a listed K3 method+path.
    """
    from intake.app import PUBLIC_ROUTE_FAMILIES

    assert set(PUBLIC_ROUTE_FAMILIES) == {
        ("POST", "/partner/v1/sites"),
        ("POST", "/partner/v1/sites/{id}/deployments"),
        ("GET", "/partner/v1/deployments/{id}"),
        ("POST", "/partner/v1/sites/{id}/domains"),
        ("GET", "/partner/v1/domains/{hostname}"),
        ("DELETE", "/partner/v1/sites/{id}"),
        ("DELETE", "/partner/v1/sites/{id}/domains/{hostname}"),
    }
    app, _fake, _private = _fresh()
    for method, path in K3_ROUTES:
        code, _, _ = _call(app, method, path, body={})
        assert code != 404, f"{method} {path} missing from public listener"
        assert code in (401, 403), f"{method} {path} unsigned → {code}"
    for method, path in NOT_PUBLIC:
        code, _, _ = _call(app, method, path, body={})
        assert code == 404, f"{method} {path} must not be public (got {code})"


@pytest.mark.req("PART-INTAKE-PROCESS")
def test_public_client_cannot_hit_internal_outbox():
    """Mesh outbox is not on the public listener, even when it holds jobs.

    What would make this fail: routing GET /internal/outbox on `application`
    so an internet client can drain signed jobs.
    """
    app, fake, private = _fresh()
    fake.outbox.put({"type": "partner-job", "planted": True})
    for method, path in (
        ("GET", "/internal/outbox"),
        ("POST", "/internal/ack"),
        ("GET", "/internal/outbox/"),
        ("POST", "/internal/ack/"),
    ):
        code, _, body = _call(app, method, path)
        assert code == 404, f"unsigned {method} {path} → {code}"
        assert b"planted" not in body
        headers = _sign(private, method, path)
        code, _, body = _call(app, method, path, headers=headers)
        assert code == 404, f"signed {method} {path} → {code}"
        assert b"planted" not in body
    assert fake.outbox.snapshot()[0]["planted"] is True


@pytest.mark.req("PART-INTAKE-PROCESS")
def test_unsigned_post_is_not_201():
    """Fail-closed verify stub: missing/invalid signature never 201/202.

    What would make this fail: a stub that returns 201 for any POST, or
    treating a missing header as authenticated.
    """
    app, _fake, private = _fresh()
    path = "/partner/v1/sites"
    payload = {"tenant_ref": "t-unsigned", "subdomain": "nope"}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    code, _, _ = _call(app, "POST", path, body=body)
    assert code not in (201, 202)
    assert code in (401, 403)

    headers = _sign(private, "POST", path, body)
    headers["X-Partner-Signature"] = ""
    code, _, _ = _call(app, "POST", path, body=body, headers=headers)
    assert code not in (201, 202)
    assert code in (401, 403)

    headers = _sign(private, "POST", path, body)
    headers["X-Partner-Signature"] = base64.b64encode(b"\x00" * 64).decode()
    code, _, _ = _call(app, "POST", path, body=body, headers=headers)
    assert code not in (201, 202)
    assert code in (401, 403)

    other = Ed25519PrivateKey.generate()
    headers = _sign(other, "POST", path, body)
    code, _, _ = _call(app, "POST", path, body=body, headers=headers)
    assert code not in (201, 202)
    assert code in (401, 403)

    code, _, _ = _call(app, "POST", "/partner/v1/sites/missing/deployments",
                       body=body)
    assert code not in (201, 202)
    assert code in (401, 403)


@pytest.mark.req("PART-K3-ENDPOINTS")
def test_post_sites_returns_201_shape():
    """Signed POST /partner/v1/sites returns 201 with id + tenant_ref.

    What would make this fail: unsigned 201 (fail-open), or a 200/202 with
    no id so the partner cannot address the site.
    """
    app, fake, private = _fresh()
    path = "/partner/v1/sites"
    payload = {
        "tenant_ref": "tenant-a",
        "subdomain": "acme",
        "template_ref": "partner-t1-static",
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = _sign(private, "POST", path, body)
    code, _hdrs, raw = _call(app, "POST", path, body=body, headers=headers)
    assert code == 201, raw
    data = json.loads(raw)
    assert data["id"]
    assert data["tenant_ref"] == "tenant-a"
    assert data["subdomain"] == "acme"
    jobs = fake.outbox.snapshot()
    assert jobs, "signed create must land on the mesh outbox"
    assert jobs[0]["type"] == "partner-job"


@pytest.mark.req("PART-K3-ENDPOINTS")
def test_post_deployments_returns_202():
    """Signed POST .../deployments returns 202 (queued), never 201.

    What would make this fail: a synchronous 201 create, or 202 without
    signing.
    """
    app, _fake, private = _fresh()
    create_path = "/partner/v1/sites"
    create_body = json.dumps(
        {"tenant_ref": "tenant-b", "subdomain": "beta"},
        separators=(",", ":"),
    ).encode("utf-8")
    created = _call(
        app, "POST", create_path, body=create_body,
        headers=_sign(private, "POST", create_path, create_body),
    )
    assert created[0] == 201, created[2]
    site_id = json.loads(created[2])["id"]
    path = f"/partner/v1/sites/{site_id}/deployments"
    body = json.dumps({"force": False}, separators=(",", ":")).encode("utf-8")
    code, _hdrs, raw = _call(
        app, "POST", path, body=body,
        headers=_sign(private, "POST", path, body),
    )
    assert code == 202, raw
    data = json.loads(raw)
    assert data["id"]
    assert data["status"] == "queued"


@pytest.mark.req("PART-K3-ENDPOINTS")
def test_delete_absent_is_204():
    """Idempotent DELETE of a missing site or domain is 204.

    What would make this fail: 404 on absent, or 204 without a signature.
    """
    app, _fake, private = _fresh()
    path = "/partner/v1/sites/missing-site"
    code, _, _ = _call(app, "DELETE", path)
    assert code in (401, 403)
    assert code != 204
    headers = _sign(private, "DELETE", path)
    code, _, raw = _call(app, "DELETE", path, headers=headers)
    assert code == 204, raw
    assert raw == b""
    domain_path = "/partner/v1/sites/missing-site/domains/gone.example"
    headers = _sign(private, "DELETE", domain_path)
    code, _, raw = _call(app, "DELETE", domain_path, headers=headers)
    assert code == 204, raw


@pytest.mark.req("PART-K1-ZERO-INBOUND-HUB")
def test_hub_urlconf_has_no_api_partner_or_mcp():
    """Hub urlpatterns contain neither /api/partner nor /mcp.

    What would make this fail: including intake URLs or adding a partner
    inbound namespace on the Hub process.
    """
    routes = _route_strings()
    blob = " ".join(routes)
    assert "api/partner" not in blob
    assert "/mcp" not in blob
    assert "partner/v1" not in blob
    assert "intake" not in blob


@pytest.mark.django_db
@pytest.mark.req("PART-K1-ZERO-INBOUND-HUB")
def test_hub_candidate_partner_and_mcp_paths_404(client):
    """Candidate Hub inbound partner/MCP paths 404.

    What would make this fail: a 200/201/302 at /api/partner or /mcp.
    """
    for path in HUB_CANDIDATE_PATHS:
        response = client.get(path)
        assert response.status_code == 404, f"GET {path} → {response.status_code}"
        response = client.post(path)
        assert response.status_code == 404, f"POST {path} → {response.status_code}"
