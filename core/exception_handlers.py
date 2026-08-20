"""API-wide exception handling (§4.5).

Validation is a security boundary, so rejected input is an *signal*, not just a 400:
a stream of malformed requests from one source is an attack in progress. These rows
feed the Hub's own throttle/fail2ban machinery in Phase 3 (§6.5 Layer 4 turned on the
Hub itself), so the row shape here must already carry what that will need.
"""
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.views import exception_handler as drf_exception_handler

from .audit import audit


def client_ip(request):
    """Client IP, honouring exactly as many proxy hops as we actually run.

    X-Forwarded-For is caller-controlled: trusting the leftmost entry lets anyone
    forge their own source IP and poison the very audit trail that is supposed to
    identify them. We count from the right, skipping our own known proxies.
    """
    from django.conf import settings

    hops = getattr(settings, "HUB_TRUSTED_PROXY_HOPS", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if hops and forwarded:
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return request.META.get("REMOTE_ADDR")


def _field_names(detail, prefix=""):
    """Field paths only — never values.

    A rejected env-var answer is a secret that failed validation. Logging the value
    would write plaintext into the append-only table that is by design the hardest
    thing in the system to redact.
    """
    names = []
    if isinstance(detail, dict):
        for key, value in detail.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            names.extend(_field_names(value, path))
    elif isinstance(detail, list):
        for item in detail:
            names.extend(_field_names(item, prefix))
    elif prefix:
        names.append(prefix)
    return names


def _codes(detail):
    codes = set()
    if isinstance(detail, dict):
        for value in detail.values():
            codes |= _codes(value)
    elif isinstance(detail, list):
        for item in detail:
            codes |= _codes(item)
    else:
        code = getattr(detail, "code", None)
        if code:
            codes.add(str(code))
    return codes


def drf_errors_to_contract(errors):
    """DRF error dict → the §4.5 shape: {field: [{code, message, hint}]}."""
    if isinstance(errors, list):
        errors = {"non_field_errors": errors}
    out = {}
    for field, msgs in errors.items():
        if not isinstance(msgs, list):
            msgs = [msgs]
        out[field] = [
            {"code": getattr(m, "code", None) or "invalid", "message": str(m), "hint": ""}
            for m in msgs
        ]
    return out


def django_validation_to_drf_detail(exc):
    """Django ValidationError → DRF detail map, keeping per-field codes."""
    if getattr(exc, "error_dict", None):
        return {
            field: [
                ErrorDetail(str(list(err)[0]), code=getattr(err, "code", None) or "invalid")
                for err in errs
            ]
            for field, errs in exc.error_dict.items()
        }
    code = getattr(exc, "code", None) or "invalid"
    return {"non_field_errors": [ErrorDetail(str(m), code=code) for m in exc.messages]}


def audited_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if isinstance(exc, ValidationError):
        request = context.get("request")
        view = context.get("view")
        actor = getattr(request, "user", None)
        if actor is not None and not getattr(actor, "is_authenticated", False):
            actor = None
        audit(
            "input_rejected",
            source="api",
            severity="warning",
            actor=actor,
            source_ip=client_ip(request) if request is not None else None,
            path=getattr(request, "path", "") if request is not None else "",
            method=getattr(request, "method", "") if request is not None else "",
            view=type(view).__name__ if view is not None else "",
            fields=sorted(set(_field_names(exc.detail))),
            codes=sorted(_codes(exc.detail)),
        )
        if response is not None:
            # DemoJobView already returns this wrap; raise_exception paths must too.
            response.data = {"errors": drf_errors_to_contract(exc.detail)}

    return response
