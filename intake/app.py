"""Stdlib WSGI public listener — six K3 families under /partner/v1/ only.

Mesh /internal/outbox and /internal/ack are not routed here. Routing iterates
PUBLIC_ROUTE_FAMILIES so a 7th family cannot hide in a second table.
"""
import json
import re

from intake.fake import FakeIntake
from intake.verify import SignatureRejected, verify

PUBLIC_ROUTE_FAMILIES = (
    ("POST", "/partner/v1/sites"),
    ("POST", "/partner/v1/sites/{id}/deployments"),
    ("GET", "/partner/v1/deployments/{id}"),
    ("POST", "/partner/v1/sites/{id}/domains"),
    ("GET", "/partner/v1/domains/{hostname}"),
    ("DELETE", "/partner/v1/sites/{id}"),
    ("DELETE", "/partner/v1/sites/{id}/domains/{hostname}"),
)

_COMPILED = tuple(
    (method, path, re.compile("^" + re.sub(r"\{[^}]+\}", r"([^/]+)", path) + "$"))
    for method, path in PUBLIC_ROUTE_FAMILIES
)


def _read_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        length = 0
    if length <= 0:
        return b""
    return environ["wsgi.input"].read(length)


def _partner_headers(environ):
    return {
        "X-Partner-Timestamp": environ.get("HTTP_X_PARTNER_TIMESTAMP", ""),
        "X-Partner-Nonce": environ.get("HTTP_X_PARTNER_NONCE", ""),
        "X-Partner-Key-Id": environ.get("HTTP_X_PARTNER_KEY_ID", ""),
        "X-Partner-Signature": environ.get("HTTP_X_PARTNER_SIGNATURE", ""),
    }


def _json(start_response, status, payload):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(raw))),
    ])
    return [raw]


def _empty(start_response, status):
    start_response(status, [("Content-Length", "0")])
    return [b""]


def _match(method, path):
    for known_method, template, cre in _COMPILED:
        if known_method != method:
            continue
        found = cre.match(path)
        if found:
            return template, found.groups()
    return None, ()


def _parse_json(body):
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def _dispatch(state, method, template, groups, body, start_response):
    try:
        payload = _parse_json(body)
    except (ValueError, UnicodeDecodeError):
        return _empty(start_response, "400 Bad Request")

    if template == "/partner/v1/sites" and method == "POST":
        site_id = state.new_id("site")
        site = {
            "id": site_id,
            "tenant_ref": payload.get("tenant_ref", ""),
            "subdomain": payload.get("subdomain", ""),
            "status": "created",
        }
        if "template_ref" in payload:
            site["template_ref"] = payload["template_ref"]
        state.sites[site_id] = site
        state.outbox.put({
            "type": "partner-job",
            "action": "site.create",
            "site_id": site_id,
            "payload": dict(site),
        })
        return _json(start_response, "201 Created", site)

    if template == "/partner/v1/sites/{id}/deployments" and method == "POST":
        site_id = groups[0]
        dep_id = state.new_id("dep")
        dep = {"id": dep_id, "site_id": site_id, "status": "queued"}
        state.deployments[dep_id] = dep
        state.outbox.put({
            "type": "partner-job",
            "action": "deployment.create",
            "deployment_id": dep_id,
            "payload": dict(dep),
        })
        return _json(start_response, "202 Accepted", {
            "id": dep_id, "status": "queued",
        })

    if template == "/partner/v1/deployments/{id}" and method == "GET":
        dep = state.deployments.get(groups[0])
        if dep is None:
            return _empty(start_response, "404 Not Found")
        return _json(start_response, "200 OK", dep)

    if template == "/partner/v1/sites/{id}/domains" and method == "POST":
        hostname = payload.get("hostname") or payload.get("domain") or ""
        record = {
            "hostname": hostname,
            "site_id": groups[0],
            "cname": f"{hostname}.cname.invalid",
            "txt": f"ownership={hostname}",
        }
        state.domains[hostname] = record
        state.outbox.put({
            "type": "partner-job",
            "action": "domain.create",
            "payload": dict(record),
        })
        return _json(start_response, "201 Created", record)

    if template == "/partner/v1/domains/{hostname}" and method == "GET":
        record = state.domains.get(groups[0])
        if record is None:
            return _empty(start_response, "404 Not Found")
        return _json(start_response, "200 OK", record)

    if template == "/partner/v1/sites/{id}" and method == "DELETE":
        state.sites.pop(groups[0], None)
        return _empty(start_response, "204 No Content")

    if template == "/partner/v1/sites/{id}/domains/{hostname}" and method == "DELETE":
        state.domains.pop(groups[1], None)
        return _empty(start_response, "204 No Content")

    return _empty(start_response, "404 Not Found")


def make_application(state=None):
    if state is None:
        state = FakeIntake()

    def application(environ, start_response):
        method = (environ.get("REQUEST_METHOD") or "GET").upper()
        path = environ.get("PATH_INFO") or "/"
        template, groups = _match(method, path)
        if template is None:
            return _empty(start_response, "404 Not Found")
        body = _read_body(environ)
        try:
            verify(method, path, body, _partner_headers(environ), state.public_keys)
        except SignatureRejected:
            return _empty(start_response, "401 Unauthorized")
        return _dispatch(state, method, template, groups, body, start_response)

    return application


application = make_application()
