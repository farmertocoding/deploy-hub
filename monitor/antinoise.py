"""Anti-noise engine (D-038, alert-protocol §4).

observe(fingerprint, ok) is the probe-level hysteresis API. after_raise(row)
sees a just-filed Finding and applies flap / suppress / ack / grouping
candidates / storm / quiet-hours priority. Delivery (ntfy) is Task 7.
"""
from datetime import datetime, timedelta

from django.utils import timezone

from core.findings import resolve
from core.models import AlertState, Finding, Site, Target
from monitor.alerts import raise_alert

OPEN_AFTER = 3
CLOSE_AFTER = 2
FLAP_WINDOW = timedelta(minutes=30)
FLAP_CYCLES = 3
GROUP_P2_WINDOW_S = 600
STORM_WINDOW = timedelta(minutes=10)
STORM_LIMIT = 10  # >10 pushes in the window
PUSH_LOG_FP = "__pushes__"
STORM_STATE_FP = "__storm__"
STORM_FINDING_FP = "alert-storm"

_after_raise_depth = 0


def observe(fingerprint, ok, *, now=None):
    """Open after 3 consecutive failures; close after 2 consecutive successes."""
    now = now or timezone.now()
    _maybe_resolve_flap(fingerprint, now)
    state, _ = AlertState.objects.get_or_create(fingerprint=fingerprint)
    if ok:
        state.consecutive_ok += 1
        state.consecutive_fail = 0
        state.save(update_fields=["consecutive_ok", "consecutive_fail"])
        if _is_open(state) and state.consecutive_ok >= CLOSE_AFTER:
            return _close(state, fingerprint, now)
        return None
    state.consecutive_fail += 1
    state.consecutive_ok = 0
    state.save(update_fields=["consecutive_fail", "consecutive_ok"])
    if state.consecutive_fail >= OPEN_AFTER and not _is_open(state):
        return _open(state, fingerprint, now)
    return None


def flap_check(fingerprint, *, now=None):
    """≥3 open/close cycles in 30 min → one P2 FLAPPING."""
    now = now or timezone.now()
    state = AlertState.objects.filter(fingerprint=fingerprint).first()
    if state is None or _cycle_count(state, now) < FLAP_CYCLES:
        return None
    flap_fp = _flap_fp(fingerprint)
    existing = Finding.objects.filter(fingerprint=flap_fp).first()
    if existing is not None and existing.state != Finding.State.RESOLVED:
        return existing
    entity = _entity_of(fingerprint)
    cycles = _cycle_count(state, now)
    return raise_alert(
        "FLAPPING",
        entity,
        fingerprint=flap_fp,
        source_engine="monitor.antinoise",
        title="FLAPPING",
        body=(
            f"{entity} opened and closed {cycles} times in 30 minutes. "
            "Individual transitions are suppressed until 30 minutes stable."
        ),
        fix_action="Find the oscillating cause; do not chase each flap.",
    )


def suppressed_by(entity):
    """Host-down suppresses its sites; zone-down suppresses its hosts."""
    kind, _, name = entity.partition(":")
    if kind == "site":
        site = (
            Site.objects.filter(name=name)
            .select_related("primary_target", "primary_target__zone")
            .first()
        )
        if site is None or site.primary_target_id is None:
            return None
        host = site.primary_target.host
        if _fingerprint_open(f"host-down:{host}"):
            return f"host:{host}"
        zone = site.primary_target.zone
        if zone is not None and _fingerprint_open(f"zone-down:{zone.slug}"):
            return f"zone:{zone.slug}"
        return None
    if kind == "host":
        target = Target.objects.filter(host=name).select_related("zone").first()
        if target is None:
            return None
        if _fingerprint_open(f"zone-down:{target.zone.slug}"):
            return f"zone:{target.zone.slug}"
        return None
    return None


def group_p2(window=GROUP_P2_WINDOW_S, *, now=None, mark=True):
    """A single P2 is not delayed; >1 P2 in `window` seconds → one grouped push.

    ``mark=False`` leaves the window pending so a caller can stamp
    delivered only after a successful publish.
    """
    now = now or timezone.now()
    log = _push_log()
    events = list(log.transitions or [])
    pending = []
    for event in events:
        if event.get("delivered") or event.get("severity") != "p2":
            continue
        at = _parse_dt(event["at"])
        if (now - at).total_seconds() <= window:
            pending.append(event)
    if not pending:
        return []
    findings = []
    seen = set()
    for event in pending:
        fp = event["fingerprint"]
        if fp in seen:
            continue
        seen.add(fp)
        row = Finding.objects.filter(fingerprint=fp).first()
        if row is not None:
            findings.append(row)
    pending_fps = {event["fingerprint"] for event in pending}
    if mark:
        mark_p2_delivered_fps(pending_fps)
    return [{"findings": findings, "grouped": len(findings) > 1}]


def mark_p2_delivered(findings):
    mark_p2_delivered_fps({row.fingerprint for row in findings})


def mark_p2_delivered_fps(fps):
    if not fps:
        return
    log = _push_log()
    events = list(log.transitions or [])
    for event in events:
        if event.get("severity") == "p2" and event["fingerprint"] in fps:
            event["delivered"] = True
    log.transitions = events
    log.save(update_fields=["transitions"])


def storm_breaker(now):
    """>10 pushes/10 min → one P1 ALERT STORM (n); exit when the rate drops."""
    now = now or timezone.now()
    recent = _recent_pushes(now)
    storm, _ = AlertState.objects.get_or_create(fingerprint=STORM_STATE_FP)
    if len(recent) > STORM_LIMIT:
        if not _is_open(storm):
            storm.opened_at = now
            storm.closed_at = None
            storm.last_push_at = now
            storm.save()
            return raise_alert(
                "ALERT STORM (n)",
                "fleet",
                fingerprint=STORM_FINDING_FP,
                source_engine="monitor.antinoise",
                title=f"ALERT STORM ({len(recent)})",
                body=(
                    f"{len(recent)} pushes in 10 minutes. "
                    "Collapsing to 10-minute summaries until the rate drops."
                ),
                fix_action="Find the noisy source; do not ack individual pages.",
            )
        if storm.last_push_at is None or now - storm.last_push_at >= STORM_WINDOW:
            storm.last_push_at = now
            storm.save(update_fields=["last_push_at"])
            return raise_alert(
                "ALERT STORM (n)",
                "fleet",
                fingerprint=STORM_FINDING_FP,
                source_engine="monitor.antinoise",
                title=f"ALERT STORM ({len(recent)})",
                body=(
                    f"{len(recent)} pushes in 10 minutes. "
                    "Collapsing to 10-minute summaries until the rate drops."
                ),
                fix_action="Find the noisy source; do not ack individual pages.",
            )
        return Finding.objects.filter(fingerprint=STORM_FINDING_FP).first()
    if _is_open(storm):
        storm.closed_at = now
        storm.save(update_fields=["closed_at"])
        row = Finding.objects.filter(fingerprint=STORM_FINDING_FP).first()
        if row is not None and row.state != Finding.State.RESOLVED:
            _resolve_engine_finding(row, now)
    return None


def recovery_notice(finding, *, now=None):
    """Mandatory UP-after-N-min notice when an opened alert closes."""
    now = now or timezone.now()
    start = finding.first_seen
    state = AlertState.objects.filter(fingerprint=finding.fingerprint).first()
    if state is not None and state.opened_at is not None:
        start = state.opened_at
    minutes = max(0, int((now - start).total_seconds() // 60))
    title = f"UP after {minutes} min"
    finding.will_push = True
    finding.push_priority = "default"
    finding.respects_quiet_hours = True
    # The notice that closes the storm is not itself a storm-rate event:
    # counting it would re-cross >10 and re-open the just-resolved storm.
    counts_for_storm = finding.fingerprint != STORM_FINDING_FP
    _record_push(finding, now, title=title, counts_for_storm=counts_for_storm)
    if counts_for_storm:
        storm_breaker(now)
    return {"title": title, "finding": finding, "minutes": minutes}


def after_raise(row, *, now=None):
    """See a just-filed Finding: ack, suppress, quiet-hours priority, storm."""
    global _after_raise_depth
    now = now or timezone.now()
    if _after_raise_depth:
        _annotate_delivery(row, now)
        return row
    _after_raise_depth += 1
    try:
        _maybe_resolve_flap(row.fingerprint, now)
        storm_breaker(now)
        _annotate_delivery(row, now)
        return _after_raise_body(row, now)
    finally:
        _after_raise_depth -= 1


def _after_raise_body(row, now):
    state, _ = AlertState.objects.get_or_create(fingerprint=row.fingerprint)
    if row.state == Finding.State.ACKED:
        if state.acked_at is None:
            state.acked_at = now
            state.save(update_fields=["acked_at"])
        row.will_push = False
        return row
    if row.will_push:
        _record_push(row, now)
        state.last_push_at = now
        state.save(update_fields=["last_push_at"])
    storm_breaker(now)
    return row


def _annotate_delivery(row, now):
    is_p1 = row.severity == Finding.Severity.P1
    row.push_priority = "max" if is_p1 else "default"
    row.respects_quiet_hours = not is_p1
    row.will_push = (
        row.state not in {
            Finding.State.ACKED,
            Finding.State.RESOLVED,
            Finding.State.ACCEPTED,
        }
        and not _flap_holds(row.fingerprint, now)
        and suppressed_by(row.entity) is None
        and not _storming_except(row, now)
    )


def _storming_except(row, now):
    if row.fingerprint == STORM_FINDING_FP:
        return False
    return len(_recent_pushes(now)) > STORM_LIMIT


def _open(state, fingerprint, now):
    entity = _entity_of(fingerprint)
    if _flap_holds(fingerprint, now) or suppressed_by(entity):
        return None
    state.opened_at = now
    state.closed_at = None
    _note_transition(state, "open", now)
    state.save()
    title, body, fix_action = _open_copy(fingerprint, entity)
    return _file_open(fingerprint, entity, title, body, fix_action)


def _close(state, fingerprint, now):
    row = Finding.objects.filter(fingerprint=fingerprint).first()
    state.closed_at = now
    _note_transition(state, "close", now)
    state.save()
    if row is not None and row.state != Finding.State.RESOLVED:
        resolve(row)
        row.refresh_from_db()
    flap_check(fingerprint, now=now)
    if row is not None:
        return recovery_notice(row, now=now)
    return {"title": "UP after 0 min", "finding": None, "minutes": 0}


def _file_open(fingerprint, entity, title, body, fix_action):
    kwargs = dict(
        fingerprint=fingerprint,
        title=title,
        body=body,
        fix_action=fix_action,
        source_engine="monitor.antinoise",
    )
    if fingerprint.startswith("host-down:") or fingerprint.startswith("zone-down:"):
        return raise_alert("partner-aggregate-down", entity, **kwargs)
    kind = _site_down_kind(entity)
    if kind == "staging-or-flapping":
        return raise_alert("staging-or-flapping", entity, **kwargs)
    if kind == "partner-site-hard-down":
        return raise_alert("partner-site-hard-down", entity, **kwargs)
    return raise_alert("prod-site-hard-down", entity, **kwargs)


def _site_down_kind(entity):
    """§2 site-down class from Site/Target env/role (or zone purpose)."""
    kind, _, name = entity.partition(":")
    if kind != "site":
        return "prod-site-hard-down"
    site = (
        Site.objects.filter(name=name)
        .select_related("primary_target", "primary_target__zone", "dns_zone")
        .first()
    )
    if site is None:
        return "prod-site-hard-down"
    label = _env_role_label(site)
    if label == "partner":
        return "partner-site-hard-down"
    if label in {"staging", "experiment", "test"}:
        return "staging-or-flapping"
    return "prod-site-hard-down"


def _env_role_label(site):
    for obj in (site, getattr(site, "primary_target", None)):
        if obj is None:
            continue
        for attr in ("tier", "role", "env"):
            raw = getattr(obj, attr, None)
            if raw in (None, ""):
                continue
            return str(getattr(raw, "value", raw)).lower()
    zone = getattr(getattr(site, "primary_target", None), "zone", None)
    if zone is not None:
        purpose = getattr(zone, "purpose", None)
        if purpose not in (None, ""):
            return str(getattr(purpose, "value", purpose)).lower()
    dns = getattr(site, "dns_zone", None)
    if dns is not None:
        purpose = getattr(dns, "purpose", None)
        if purpose not in (None, ""):
            return str(getattr(purpose, "value", purpose)).lower()
    return "prod"


def _open_copy(fingerprint, entity):
    if fingerprint.startswith("host-down:"):
        host = entity.partition(":")[2]
        names = list(
            Site.objects.filter(primary_target__host=host)
            .order_by("name")
            .values_list("name", flat=True)
        )
        listed = ", ".join(f"site:{n}" for n in names) or "(none)"
        return (
            f"Host {host} is down",
            f"Host {host} is unreachable. Suppressed: {listed}.",
            "Check the host: SSH, disk, and docker.",
        )
    if fingerprint.startswith("zone-down:"):
        slug = entity.partition(":")[2]
        hosts = list(
            Target.objects.filter(zone__slug=slug)
            .order_by("host")
            .values_list("host", flat=True)
        )
        listed = ", ".join(f"host:{h}" for h in hosts) or "(none)"
        return (
            f"Zone {slug} is down",
            f"All targets in zone {slug} are unreachable. Suppressed: {listed}.",
            "Check zone connectivity before paging every host.",
        )
    name = entity.partition(":")[2]
    return (
        f"Site {name} is down",
        f"Three consecutive probes failed for {name}.",
        "Check docker ps on the target; restart the container.",
    )


def _entity_of(fingerprint):
    prefix, _, rest = fingerprint.partition(":")
    if prefix.endswith("-down"):
        return f"{prefix[:-5]}:{rest}"
    if prefix == "FLAPPING":
        return _entity_of(rest)
    return fingerprint


def _flap_fp(fingerprint):
    return f"FLAPPING:{fingerprint}"


def _is_open(state):
    return state.opened_at is not None and state.closed_at is None


def _fingerprint_open(fingerprint):
    state = AlertState.objects.filter(fingerprint=fingerprint).first()
    return state is not None and _is_open(state)


def _note_transition(state, event, now):
    events = list(state.transitions or [])
    events.append({"at": now.isoformat(), "event": event})
    state.transitions = events


def _cycle_count(state, now):
    cycles = 0
    opened = False
    for event in state.transitions or []:
        at = _parse_dt(event["at"])
        if now - at > FLAP_WINDOW:
            continue
        if event["event"] == "open":
            opened = True
        elif event["event"] == "close" and opened:
            cycles += 1
            opened = False
    return cycles


def _flap_holds(fingerprint, now):
    if fingerprint.startswith("FLAPPING:"):
        return False
    flap = (
        Finding.objects.filter(fingerprint=_flap_fp(fingerprint))
        .exclude(state=Finding.State.RESOLVED)
        .first()
    )
    if flap is None:
        return False
    state = AlertState.objects.filter(fingerprint=fingerprint).first()
    if state is None or not state.transitions:
        return True
    last = _parse_dt(state.transitions[-1]["at"])
    return now - last < FLAP_WINDOW


def _maybe_resolve_flap(fingerprint, now):
    if fingerprint.startswith("FLAPPING:"):
        base = fingerprint[len("FLAPPING:"):]
        flap_fp = fingerprint
    else:
        base = fingerprint
        flap_fp = _flap_fp(fingerprint)
    flap = (
        Finding.objects.filter(fingerprint=flap_fp)
        .exclude(state=Finding.State.RESOLVED)
        .first()
    )
    if flap is None:
        return
    state = AlertState.objects.filter(fingerprint=base).first()
    if state is None or not state.transitions:
        return
    last = _parse_dt(state.transitions[-1]["at"])
    if now - last >= FLAP_WINDOW:
        _resolve_engine_finding(flap, now)


def _resolve_engine_finding(row, now):
    if row.state == Finding.State.RESOLVED:
        return
    resolve(row)
    row.refresh_from_db()
    recovery_notice(row, now=now)


def _push_log():
    state, _ = AlertState.objects.get_or_create(fingerprint=PUSH_LOG_FP)
    return state


def _record_push(row, now, title=None, *, counts_for_storm=True):
    log = _push_log()
    events = list(log.transitions or [])
    event = {
        "at": now.isoformat(),
        "fingerprint": row.fingerprint,
        "severity": row.severity,
        "delivered": False,
        "title": title or row.title,
    }
    if not counts_for_storm:
        event["counts_for_storm"] = False
    events.append(event)
    log.transitions = events
    log.last_push_at = now
    log.save()


def _recent_pushes(now):
    log = AlertState.objects.filter(fingerprint=PUSH_LOG_FP).first()
    if log is None:
        return []
    recent = []
    for event in log.transitions or []:
        if event.get("counts_for_storm") is False:
            continue
        at = _parse_dt(event["at"])
        if now - at <= STORM_WINDOW:
            recent.append(event)
    return recent


def _parse_dt(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _install_hook():
    """The only after_raise seam: alerts.after_raise is this module's hook."""
    from monitor import alerts
    alerts.after_raise = after_raise


_install_hook()
