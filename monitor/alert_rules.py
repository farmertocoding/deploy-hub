"""The alert-protocol §2 rules table and classify() (D-037).

Every alert class the Hub may emit is a row here first. classify(kind, **facts)
returns that row's severity, or UnclassifiedAlert — an unregistered kind cannot
ship. A few kinds escalate from the table default when facts say so (warm-up
with no ready instance, partner-tier aggregates, a Hub-surface CVE). Hysteresis
and flap/storm live in Task 6; this module only names the class and severity.
"""
from typing import NamedTuple


class UnclassifiedAlert(LookupError):
    """Raised when classify() is asked for a kind with no table row (D-037)."""

    def __init__(self, kind):
        self.kind = kind
        super().__init__(
            f"unclassified alert kind {kind!r} — add a row to "
            "monitor/alert_rules.py before it can ship (D-037)"
        )


class AlertRule(NamedTuple):
    kind: str
    severity: str
    condition_text: str
    source_clause: str
    restart_trigger: bool = False


def _r(kind, severity, condition_text, source_clause, restart_trigger=False):
    return AlertRule(
        kind=kind,
        severity=severity,
        condition_text=condition_text,
        source_clause=source_clause,
        restart_trigger=restart_trigger,
    )


# Transcribed clause-by-clause from alert-protocol.md §2. condition_text is the
# bullet body (UPDATE prefix stripped) so the P1 parser can bijection-match.
RULES = (
    # ── P1 — wake me ────────────────────────────────────────────────────
    _r(
        "prod-site-hard-down",
        "p1",
        "Prod-tier site hard-down > 5 min (3 consecutive failed probes, "
        "and the canary check passed — see §5)",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "hub-down",
        "p1",
        "The Hub itself down (dead-man's switch fired — external, see §5)",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "hub-db-or-backup-failure",
        "p1",
        "Hub database failure, or nightly backup failed/missing",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "attack-playbook-engaged",
        "p1",
        "Attack playbook engaged (Under-Attack mode flipped, edge bans pushed)",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "budget-cap-hit",
        "p1",
        "Any budget cap hit (cloud spend, partner quota-abuse trip, "
        "test-plane $10 alarm)",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "vault-kek-or-mass-secret",
        "p1",
        "Vault/KEK unlock failure at service start; any anomaly alert on "
        "mass secret access",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "ssh-host-key-mismatch",
        "p1",
        "SSH host-key mismatch on any target (possible MITM/hijack — "
        "never auto-retried)",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "ssh-rotation-incomplete",
        "p1",
        "SSH key rotation started but did not finish; old key remains the login path",
        "D-064 / phase-4-design-note.md §7 C8",
    ),
    _r(
        "disk-critical",
        "p1",
        "Disk > 95% on any host (at 95% you're minutes from an outage; "
        "85% is P2)",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "partner-kill-switch",
        "p1",
        "Partner API kill-switch auto-triggered (abuse detection)",
        "alert-protocol.md §2 P1",
    ),
    _r(
        "partner-intake-unreachable",
        "p1",
        "Partner Intake unreachable > 5 min (the partner-facing platform "
        "is down)",
        "alert-protocol.md §2 P1 / review3 §O1",
    ),
    _r(
        "cert-expiry-critical",
        "p1",
        "Uploaded cert < 7 d; auto-renewed cert < 1 d (see cert-threshold "
        "note below)",
        "alert-protocol.md §2 P1 / review3 §V9",
    ),
    _r(
        "instance-warmup-no-ready",
        "p1",
        "Instance warm-up exceeded budget escalates to P1 **only if no "
        "ready instance is serving** (otherwise P2, see below)",
        "alert-protocol.md §2 P1 / review3 §O1",
    ),
    _r(
        "partner-aggregate-down",
        "p1",
        "Partner-tier sites escalate to P1 **only on aggregate signals**: "
        "N partner sites down simultaneously, or a partner-tier target "
        "host down (a single partner-tier site hard-down is P2, see below)",
        "alert-protocol.md §2 P1 / review3 §O1",
    ),
    # ── P2 — today ──────────────────────────────────────────────────────
    _r(
        "staging-or-flapping",
        "p2",
        "Staging/experiment-tier site down; prod site *flapping* "
        "(collapsed to one alert, see §4)",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "error-rate-or-latency",
        "p2",
        "Error rate (5xx) above threshold; p95 latency > 2× 7-day baseline "
        "and rising",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "resource-pressure",
        "p2",
        "Disk > 85%; RAM/CPU sustained > 90% without a scale event",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "drift-unrepaired",
        "p2",
        "Drift finding the reconciler could **not** auto-repair "
        "(3 failed convergences → backoff alert), or \"something is "
        "fighting the reconciler\"",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "ssh-rotation-stale-key",
        "p2",
        "Old SSH pubkey still authenticates after rotation intended to revoke it",
        "D-064 / phase-4-design-note.md §7 C8",
    ),
    _r(
        "cert-expiry-warning",
        "p2",
        "Cert expiring: auto-renewed certs < 7 d (renewal is broken if "
        "this ever fires); uploaded certs < 21 d",
        "alert-protocol.md §2 P2 / review3 §V9",
    ),
    _r(
        "auth-brute-force",
        "p2",
        "fail2ban mass-ban spike / auth brute-force pattern; repeated "
        "partner signature failures",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "drill-missed",
        "p2",
        "A scheduled drill failed **or did not run** (a skipped drill is "
        "a finding, not a silence)",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "hub-egress-degraded",
        "p2",
        "Hub egress degraded (canary probe failing — my monitoring is blind)",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "clock-skew",
        "p2",
        "Clock skew > 30 s on any target",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "scale-out-proposal",
        "p2",
        "Scale-out proposal awaiting approval (propose mode) — push with "
        "the approve action link",
        "alert-protocol.md §2 P2",
    ),
    _r(
        "feed-data-stale",
        "p2",
        "Feed data-stale beyond per-feed threshold (market-calendar-aware) "
        "= **P2 push** — arguably the single alert Joseph most wants from "
        "this project; **never a restart trigger** (§N3)",
        "alert-protocol.md §2 P2 / review3 §O1 / §N3",
        restart_trigger=False,
    ),
    _r(
        "instance-warmup-exceeded",
        "p2",
        "Instance warm-up exceeded budget = **P2**, escalating P1 only if "
        "no ready instance is serving",
        "alert-protocol.md §2 P2 / review3 §O1",
    ),
    _r(
        "scheduled-job-failed",
        "p2",
        "Scheduled app job failed = **P2 with consecutive-failure "
        "hysteresis**; individual run failures go to the P3 digest",
        "alert-protocol.md §2 P2 / review3 §O1",
    ),
    _r(
        "partner-site-hard-down",
        "p2",
        "Partner-tier site hard-down = **P2 by default** (not the prod-P1 "
        "row, not the staging row), escalating to P1 only on the aggregate "
        "signals listed above",
        "alert-protocol.md §2 P2 / review3 §O1",
    ),
    _r(
        "hub-outbox-poll-failing",
        "p2",
        "Hub→outbox poll failing N cycles = **P2**",
        "alert-protocol.md §2 P2 / review3 §O1",
    ),
    _r(
        "target-cron-stale",
        "p2",
        "Target cron job failed/stale = **P2** (interim: both delivered "
        "cron scripts curl the ntfy P2 topic on failure — two lines each "
        "— so `update-cloudflare-ufw.sh` going stale can't silently rot "
        "toward blocked users)",
        "alert-protocol.md §2 P2 / review3 §O1",
    ),
    # ── P3 — digest ─────────────────────────────────────────────────────
    _r(
        "advice-tier",
        "p3",
        "Advice-tier findings, security-score/topology-score changes",
        "alert-protocol.md §2 P3",
    ),
    _r(
        "drift-auto-repaired",
        "p3",
        "Drift found *and* auto-repaired (with what/when/command)",
        "alert-protocol.md §2 P3",
    ),
    _r(
        "completed-event",
        "p3",
        "Deploys completed (yours and partners'), scale episodes completed "
        "with cost, cert renewals succeeded",
        "alert-protocol.md §2 P3",
    ),
    _r(
        "dependency-advisory",
        "p3",
        "pip-audit / dependency monthly report, Django/DRF security-release "
        "notices (jumps to P2 if the CVE matches the Hub's own surface)",
        "alert-protocol.md §2 P3",
    ),
    _r(
        "weekly-trends",
        "p3",
        "Uptime/traffic weekly trends; retention janitor and backup-restore "
        "drill summaries",
        "alert-protocol.md §2 P3",
    ),
    _r(
        "cert-expiry-advisory",
        "p3",
        "Uploaded cert < 45 d",
        "alert-protocol.md §2 P3 / review3 §V9",
    ),
    _r(
        "scheduled-job-run-failed",
        "p3",
        "Individual scheduled-job run failures (P2 only on consecutive "
        "failures, above)",
        "alert-protocol.md §2 P3 / review3 §O1",
    ),
    # ── Phase-3 kinds that §2 does not name as their own bullet ─────────
    _r(
        "deadman-post-failure",
        "p2",
        "Dead-man POST to the external receiver failed or was unreachable",
        "alert-protocol.md §5 / D-039",
    ),
    _r(
        "cf-token-scope",
        "p2",
        "Cloudflare token scope drift (daily audit) or construction-time "
        "scope refusal",
        "D-034 / SEC-B5",
    ),
    _r(
        "tailscale-unknown-device",
        "p2",
        "A Tailscale device the Hub did not create appeared on the tailnet",
        "D-058",
    ),
    _r(
        "unproxied-cert-refusal",
        "p2",
        "Unproxied public site refused Hub-central DNS-01; named Finding "
        "and Sites-screen state",
        "D-035",
    ),
    # ── §4 anti-noise kinds (not §2 bullets) ────────────────────────────
    _r(
        "FLAPPING",
        "p2",
        "≥3 open/close cycles in 30 min → one FLAPPING alert (P2); "
        "individual transitions suppressed until stable for 30 min",
        "alert-protocol.md §4 / D-038",
    ),
    _r(
        "ALERT STORM (n)",
        "p1",
        ">10 pushes in 10 minutes → one ALERT STORM (n alerts) P1 and "
        "10-min summaries until the rate drops",
        "alert-protocol.md §4 / D-038",
    ),
    _r(
        "pager-email-failed",
        "p2",
        "A failed alert email send; the push path must not block",
        "alert-protocol.md §1 / D-037",
    ),
    _r(
        "ntfy-token-revoke-pending",
        "p2",
        "Target publish token marked revoked; one manual ntfy-account step remains",
        "D-036 / review3 §M3",
    ),
    _r(
        "pager-drill",
        "p1",
        "Monthly pager test: a scheduled synthetic P1 (TEST — ack me) "
        "verifies the whole path phone-deep",
        "alert-protocol.md §7 / ALERT-PAGER-DRILL",
    ),
)

RULES_BY_KIND = {rule.kind: rule for rule in RULES}

# Plural "N partner sites" — two or more, or a partner-tier host down.
PARTNER_AGGREGATE_N = 2


def classify(kind, **facts):
    """Return p1/p2/p3 for a registered kind, or raise UnclassifiedAlert."""
    rule = RULES_BY_KIND.get(kind)
    if rule is None:
        raise UnclassifiedAlert(kind)

    if kind == "instance-warmup-exceeded" and facts.get(
        "ready_instance_serving"
    ) is False:
        return "p1"

    if kind == "partner-site-hard-down" and _partner_aggregate(facts):
        return "p1"

    if kind == "scheduled-job-failed" and facts.get("consecutive") is False:
        return "p3"

    if kind == "dependency-advisory" and (
        facts.get("hub_surface") or facts.get("cve_matches_hub")
    ):
        return "p2"

    if kind == "drill-missed" and facts.get("drill_kind") == "pager":
        return "p1"

    return rule.severity


def _partner_aggregate(facts):
    if facts.get("host_down") or facts.get("aggregate"):
        return True
    sites_down = facts.get("sites_down")
    return sites_down is not None and int(sites_down) >= PARTNER_AGGREGATE_N
