"""Uptime probe cycle (Task 8 — design note §1.8, MON-UPTIME-EVENTS).

Every probe is Hub-side HTTP through one injectable seam (the poller's
ls_remote pattern): public sites by domain, mesh_only sites Hub→tailnet
against the target host — NEVER a second per-minute SSH session, which §C3
exists to prevent; the collector keeps the one session budget. `UptimeEvent`
rows record state *transitions*, not samples — they are what the hysteresis
engine reads. ws-class sites additionally surface last-tick age + connection
count from the /healthz payload the collector already fetched (§O3): a
rendering rule over existing data, not new machinery.
"""
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.utils import timezone

from core.audit import audit
from core.models import Site, Target, UptimeEvent

SCHEMA_VERSION = 1
PROBE_TIMEOUT_S = 10

# Key spellings the scanner-addendum /healthz contract uses for ws-class
# tick/connection data (§O3); checked in the entry and its nested checks.
_WS_TICK_KEYS = ("last_tick_age_s", "last_tick_age", "tick_age_s")
_WS_CONN_KEYS = ("connections", "connection_count", "active_connections")


def http_probe(url, *, host=None, timeout=PROBE_TIMEOUT_S):
    """Default Hub→site HTTP seam: GET, bounded timeout, returns the status.

    A non-2xx response is still a response — HTTPError is folded into its
    code; only unreachability (URLError/OSError family) raises to the caller.
    """
    headers = {"Host": host} if host else {}
    request = Request(url, headers=headers, method="GET")
    # nosec justification: every URL is built from Site.domain / Target.host
    # with a pinned http(s) scheme — no caller input can make this file:/.
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            return response.status
    except HTTPError as error:
        return error.code


def probe_url(site):
    """(url, host_header) for one site: public by domain over HTTPS,
    mesh_only Hub→tailnet HTTP against the primary target's host."""
    path = site.liveness_path or "/healthz"
    if site.exposure == Site.Exposure.MESH_ONLY:
        return f"http://{site.primary_target.host}{path}", (site.domain or None)
    return f"https://{site.domain}{path}", None


def ws_card_metric(healthz_entry):
    """§O3 rendering rule: last-tick age + connection count out of the
    /healthz payload the collector already fetched. None when the payload
    carries no tick data — a plain HTTP site has no ws card metric."""
    if not isinstance(healthz_entry, dict):
        return None
    nested = healthz_entry.get("checks")
    pools = [healthz_entry] + ([nested] if isinstance(nested, dict) else [])
    tick = _first_key(pools, _WS_TICK_KEYS)
    connections = _first_key(pools, _WS_CONN_KEYS)
    if tick is None and connections is None:
        return None
    return {"last_tick_age_s": tick, "connections": connections}


def _first_key(pools, keys):
    for pool in pools:
        for key in keys:
            if key in pool:
                return pool[key]
    return None


def collected_healthz_entry(site):
    """The site's container entry in the healthz block of the target's last
    collect payload (containers are named site-<slug>-…, reconcile/loop.py)."""
    payload = getattr(site.primary_target, "collect_payload", None) or {}
    checks = (payload.get("healthz") or {}).get("checks") or {}
    prefix = f"site-{site.name}"
    for name, entry in sorted(checks.items()):
        if isinstance(entry, dict) and str(name).startswith(prefix):
            return entry
    return None


def record_transition(entity, kind, state, *, at=None):
    """One UptimeEvent per state CHANGE — never one per probe."""
    last = (
        UptimeEvent.objects.filter(entity=entity, kind=kind)
        .order_by("-at", "-pk")
        .first()
    )
    if last is not None and last.state == state:
        return None
    return UptimeEvent.objects.create(
        entity=entity, kind=kind, state=state, at=at or timezone.now(),
    )


def _observe(fingerprint, ok):
    """Task 6's hysteresis engine (monitor/antinoise.py::observe). Guarded
    import until that task merges — one line to unguard, never a fork."""
    try:
        from monitor.antinoise import observe
    except ImportError:
        return None
    return observe(fingerprint, ok)


def _probe_sites():
    return (
        Site.objects.filter(primary_target__status=Target.Status.READY)
        .select_related("primary_target")
        .order_by("pk")
    )


def probe_cycle(*, http_get=None, now=None):
    """Probe every site once over HTTP; record transitions; feed observe().

    A DOWN site is a completed probe. Only an unexpected internal error marks
    the cycle incomplete — and an incomplete cycle must not dead-man ping
    (§C7), because the ping's whole claim is "the pipeline proved itself
    end-to-end this minute".
    """
    get = http_get or http_probe
    results, errors = [], 0
    for site in _probe_sites():
        entity = f"site:{site.name}"
        url, host = probe_url(site)
        try:
            status = get(url, host=host, timeout=PROBE_TIMEOUT_S)
            ok = status is not None and 200 <= int(status) < 400
        except OSError as exc:  # unreachable/timeout — a DOWN result
            status, ok = None, False
            detail = type(exc).__name__
        except Exception as exc:
            errors += 1
            audit("uptime-probe-error", site, source="system",
                  severity="warning", error=type(exc).__name__)
            results.append({"entity": entity, "error": type(exc).__name__})
            continue
        else:
            detail = ""
        state = "up" if ok else "down"
        transition = record_transition(entity, "http", state, at=now)
        _observe(f"site-down:{site.name}", ok)
        row = {
            "entity": entity,
            "ok": ok,
            "status": status,
            "state": state,
            "transition": transition is not None,
        }
        if detail:
            row["detail"] = detail
        metric = ws_card_metric(collected_healthz_entry(site))
        if metric is not None:
            row["ws_metric"] = metric
        results.append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "completed": errors == 0,
        "n": len(results),
        "errors": errors,
        "results": results,
    }
