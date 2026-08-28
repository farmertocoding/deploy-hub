"""Daily SEC-B5 token-scope audit — defense-in-depth behind the wall (D-034:
dns_provider_for enforces at construction; this audit only observes and files).

For every cloudflare DnsAccount, the dns and edge refs are resolved from
their model home and observed through the SAME pinned verify + zone-set
probe construction uses (providers.cloudflare.verify_token, which routes
through observe_token — one spelling of the rule, D-046), then judged
against the account's declared DnsZone rows. Drift — a Global-API-Key
shape (refused pre-network, never sent), an inactive token, or reach into
zones no row names — files one P2 Finding per stable fingerprint
``cf-token-scope:{account_pk}:{role}``. The Origin-CA ref is checked for
presence only: no Cloudflare API can observe an Origin CA key, so presence
on the model is the auditable fact.

Every run writes a CheckRun(kind=cf_token_scope); a credential the audit
could not observe (API/network failure) marks the run FAILED rather than
guessing. No token values in Finding bodies, run results, logs (this module
logs nothing), or task args (the Beat task takes none).
"""

RESULTS_SCHEMA_VERSION = 1
SOURCE_ENGINE = "token_audit"

# The §6.5 L5 playbook's edge-token minimum on the account's zones, modelled
# now so Phase 4 consumes a recorded constant instead of inventing one (panel
# r2: the edge ref needs a model home and an audit today). Cloudflare returns
# no policy set to the token itself (D-046), so the minimum is recorded with
# each observation rather than compared against a scope list the API cannot
# produce; the zone-set probe still catches reach drift on the edge token.
EDGE_TOKEN_MINIMUM = ("Zone:Firewall Services:Edit", "Zone Settings:Edit")


def audit_cloudflare_credentials(*, timeout=20):
    """Audit every cloudflare DnsAccount's credentials; return the CheckRun."""
    from core.models import CheckRun, DnsAccount
    from monitor.drills import record_run

    accounts = []
    unobserved = False
    rows = DnsAccount.objects.filter(
        provider=DnsAccount.Provider.CLOUDFLARE
    ).order_by("pk")
    for account in rows:
        declared = {
            zone.provider_zone_id: zone.name for zone in account.zones.all()
        }
        credentials = {}
        for role, ref in (
            ("dns", account.dns_token_ref),
            ("edge", account.edge_token_ref),
            ("origin_ca", account.origin_ca_key_ref),
        ):
            entry = _audit_credential(
                account, role, ref, declared, timeout=timeout,
            )
            if role == "edge" and ref:
                entry["modelled_minimum"] = list(EDGE_TOKEN_MINIMUM)
            credentials[role] = entry
            unobserved = unobserved or entry["status"] == "error"
        accounts.append({
            "account": account.label,
            "credentials": credentials,
            "origin_ca_key_ref_present": bool(account.origin_ca_key_ref),
        })
    return record_run(
        CheckRun.Kind.CF_TOKEN_SCOPE,
        CheckRun.Status.FAILED if unobserved else CheckRun.Status.SUCCEEDED,
        {"schema_version": RESULTS_SCHEMA_VERSION, "accounts": accounts},
    )


def _audit_credential(account, role, ref, declared, *, timeout):
    """Observe one credential ref and judge it. Returns the results entry;
    files the P2 Finding itself when the observation is drift."""
    from providers import cloudflare
    from providers.registry import ScopeError

    if not ref:
        # An unconnected credential is Settings' gap and the wall's refusal
        # (both already operator-visible), not scope drift.
        return {"status": "absent"}
    try:
        observed = cloudflare.verify_token(ref, timeout=timeout)
    except ScopeError as error:
        # A named ref with no vault secret behind it: every construction
        # refuses and files its own Finding; the audit records the hole.
        return {"status": "no_secret", "detail": str(error)}
    except cloudflare.CloudflareApiError as error:
        if error.status in (401, 403):
            # Cloudflare itself rejected the credential: a revoked/deleted
            # token — the stronger form of the inactive drift, never to be
            # conflated with an outage the operator cannot act on.
            _file_drift_finding(
                account, role,
                f"Cloudflare rejected the {role} token with HTTP "
                f"{error.status} — the token was likely revoked or deleted; "
                "the wall will refuse it at the next construction",
            )
            return {
                "status": "rejected",
                "drift": "revoked",
                "http_status": error.status,
            }
        # 5xx / malformed success=false: the audit could not observe.
        return {"status": "error", "detail": str(error)}
    except cloudflare.CloudflareError as error:
        # refuse_global_api_key fired: the credential has the Global API Key
        # (or another structured) shape and was never sent over the network —
        # refused, not warned; the error text names the shape, never a value.
        _file_drift_finding(
            account, role,
            f"the {role} credential was refused by shape before any request "
            f"was sent: {error}",
        )
        return {"status": "refused_shape"}
    except OSError as error:
        # Connection failure/timeout: the audit could not observe. FAILED
        # CheckRun (via the caller) is the honest outcome, not a guess.
        return {"status": "error", "detail": type(error).__name__}

    if observed["status"] != "active":
        _file_drift_finding(
            account, role,
            f"token verify returned status {observed['status']!r}, not "
            "'active' — a dead credential the wall will refuse at the next "
            "construction",
        )
        return {"status": observed["status"] or "unknown", "drift": "inactive"}

    # Same set-size fact the wall uses (observe_token.zone_count). A
    # truncated page (total_count present and != page length) is hidden
    # reach, not a clean one-zone token.
    count = observed["zone_count"]
    visible = observed["zones"]
    if count != len(visible):
        _file_drift_finding(
            account, role,
            f"the {role} token zone-set size is {count} but the probe page "
            f"named {len(visible)} zone(s) — extra reach is hidden from "
            f"page length (D-046); the declared minimum is "
            f"{sorted(declared.values())}",
        )
        return {
            "status": "active",
            "drift": "excess_zones",
            "zone_count": count,
        }

    excess = [z for z in visible if z["id"] not in declared]
    if excess:
        names = ", ".join(f"{z['name'] or '?'} ({z['id']})" for z in excess)
        _file_drift_finding(
            account, role,
            f"the {role} token can reach zones no DnsZone row names: {names} "
            f"— the declared minimum is {sorted(declared.values())}",
        )
        return {
            "status": "active",
            "drift": "excess_zones",
            "excess_zone_ids": sorted(z["id"] for z in excess),
        }

    return {
        "status": "active",
        "drift": None,
        "zone_ids": sorted(z["id"] for z in observed["zones"]),
    }


def _file_drift_finding(account, role, description):
    """One P2 per (account, credential role) through finding() so D-045 publishes."""
    from core.findings import finding
    from core.models import Finding

    return finding(
        SOURCE_ENGINE,
        f"cf-token-scope:{account.pk}:{role}",
        workspace=account.workspace,
        severity=Finding.Severity.P2,
        entity=f"dns_account:{account.label}",
        title=f"Cloudflare {role} token scope drift on {account.label}",
        body=description,
        fix_action=(
            f"Re-issue the {role} token scoped to exactly the account's "
            "declared zones and update the DnsAccount ref"
        ),
    )
