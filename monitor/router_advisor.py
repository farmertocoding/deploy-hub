"""Tunnel-mode probe: verify nothing is forwarded on the WAN.

Default wan_probe is refuse-closed (None). Tests inject a callable that
returns {"forwards": [{"port": int, "proto": "tcp"|"udp"}, ...]}. This
module never opens a live WAN scan.
"""
from core.findings import finding, resolve
from core.models import Finding

TITLE = "Tunnel target has a WAN forward"
FIX = "Remove the WAN port mapping on the router, then Probe router."
SOURCE = "router_advisor"


def _is_tunnel(target):
    return (target.collect_payload or {}).get("tunnel") is True


def _fingerprint(target):
    return f"router-forwarded:{target.pk}"


def _open_or_acked(target):
    return Finding.objects.filter(
        fingerprint=_fingerprint(target),
        state__in=(Finding.State.OPEN, Finding.State.ACKED),
    ).first()


def _body(forwards):
    named = ", ".join(f"{row['port']}/{row['proto']}" for row in forwards)
    return (
        f"WAN forward {named} is mapped. "
        f"A forwarded port bypasses Cloudflare Tunnel."
    )


def router_advice_for(target):
    """Read-only advice for GET detail. Does not run wan_probe."""
    row = _open_or_acked(target)
    return {
        "mode": "tunnel" if _is_tunnel(target) else "not_tunnel",
        "forwarded": bool(row),
        "finding_id": row.pk if row else None,
        "title": row.title if row else "",
        "body": row.body if row else "",
    }


def probe_nothing_forwarded(target, *, wan_probe=None):
    """File or resolve router-forwarded:{pk}. Refuse-closed when wan_probe is None."""
    if not _is_tunnel(target):
        return {
            "mode": "not_tunnel",
            "forwarded": False,
            "finding_id": None,
            "title": "",
            "body": "",
        }
    if wan_probe is None:
        return {
            "mode": "no_seam",
            "forwarded": False,
            "finding_id": None,
            "title": "",
            "body": "",
        }
    forwards = list((wan_probe() or {}).get("forwards") or [])
    if forwards:
        row = finding(
            SOURCE,
            _fingerprint(target),
            severity=Finding.Severity.P2,
            entity=f"target:{target.pk}",
            title=TITLE,
            body=_body(forwards),
            fix_action=FIX,
        )
        return {
            "mode": "tunnel",
            "forwarded": True,
            "finding_id": row.pk,
            "title": row.title,
            "body": row.body,
        }
    row = _open_or_acked(target)
    if row is not None:
        resolve(row, source="system")
    return {
        "mode": "tunnel",
        "forwarded": False,
        "finding_id": None,
        "title": "",
        "body": "",
    }
