#!/usr/bin/env bash
# hub-upgrade.sh v2026-08-22
# Canonical: scripts/hub-upgrade.sh (server-hardening.md)
# C6: refuse running Deployment → pg_dump Hub DB → keep previous image →
# pull + build → migrate → SIGTERM Celery → smoke login + one probe cycle.
# --rollback restores the previous kept image.
# HUB_DRAIN_TIMEOUT_S turns the refusal into a hold: wait for running
# Deployments to drain, then refuse only if some are still running.
set -euo pipefail

SCRIPT_VERSION="2026-08-22"
DRY_RUN="${DRY_RUN:-0}"
HUB_DB_NAME="${HUB_DB_NAME:-hub}"
HUB_DUMP_DIR="${HUB_DUMP_DIR:-/var/lib/hub-upgrade}"
HUB_IMAGE="${HUB_IMAGE:-deploy-hub-web}"
HUB_PREVIOUS_IMAGE="${HUB_PREVIOUS_IMAGE:-deploy-hub-web:previous}"
HUB_SMOKE_URL="${HUB_SMOKE_URL:-http://127.0.0.1:8000/api/auth/me/}"
HUB_LOGIN_URL="${HUB_LOGIN_URL:-http://127.0.0.1:8000/api/auth/login/}"
HUB_CHECK_RUNNING="${HUB_CHECK_RUNNING:-}"
HUB_DRAIN_TIMEOUT_S="${HUB_DRAIN_TIMEOUT_S:-}"
HUB_DRAIN_POLL_S="${HUB_DRAIN_POLL_S:-10}"

die() {
    echo "hub-upgrade.sh: $*" >&2
    exit 1
}

run() {
    if [[ "${DRY_RUN}" == "1" ]]; then
        printf 'DRY_RUN:'
        printf ' %q' "$@"
        printf '\n'
        return 0
    fi
    "$@"
}

usage() {
    cat <<'EOF'
hub-upgrade.sh — upgrade the Hub host (C6).

Usage:
  hub-upgrade.sh
      Refuse if a Deployment is running, pg_dump the Hub DB (not the KEK
      keyfile), keep the current image, pull + build, migrate, SIGTERM
      Celery, smoke login, one probe cycle.
  hub-upgrade.sh --rollback
      Restore the previous kept image (tagged before the last upgrade) and
      recreate Hub app services.
  hub-upgrade.sh --help

DRY_RUN=1 prints the plan and does not run docker, pg_dump, or systemctl.
HUB_CHECK_RUNNING   command whose stdout is a count of running Deployments
                    (default: manage.py one-liner on Deployment.status=running).
HUB_DRAIN_TIMEOUT_S unset (default): refuse immediately if any Deployment is
                    running. Set to a number of seconds (600 is the suggested
                    ops value) to hold: re-check until the count reaches 0,
                    then refuse only if still running at the timeout.
HUB_DRAIN_POLL_S    seconds between drain re-checks (default 10).
EOF
}

count_running_deployments() {
    local raw
    if [[ -n "${HUB_CHECK_RUNNING}" ]]; then
        raw="$(bash -c "${HUB_CHECK_RUNNING}")"
    else
        raw="$(python manage.py shell -c 'from deploys.models import Deployment; print(Deployment.objects.filter(status="running").count())')"
    fi
    raw="${raw//[$'\t\n\r ']/}"
    printf '%s\n' "${raw}"
}

checked_running_count() {
    local count
    count="$(count_running_deployments)"
    if [[ ! "${count}" =~ ^[0-9]+$ ]]; then
        die "running-deployment check did not print a count (got ${count:-empty})"
    fi
    printf '%s\n' "${count}"
}

# Hold-through-build (D-027): sleep and re-check until the running count
# reaches 0 or HUB_DRAIN_TIMEOUT_S elapses. Prints the last count seen.
wait_for_drain() {
    local count elapsed
    count="$1"
    elapsed=0
    while ((count > 0 && elapsed < HUB_DRAIN_TIMEOUT_S)); do
        echo "hub-upgrade.sh: waiting for ${count} running Deployment(s) to drain (${elapsed}s of ${HUB_DRAIN_TIMEOUT_S}s)" >&2
        sleep "${HUB_DRAIN_POLL_S}"
        elapsed=$((elapsed + HUB_DRAIN_POLL_S))
        count="$(checked_running_count)"
    done
    printf '%s\n' "${count}"
}

refuse_if_running() {
    local count
    count="$(checked_running_count)"
    if ((count > 0)) && [[ -n "${HUB_DRAIN_TIMEOUT_S}" ]]; then
        if [[ ! "${HUB_DRAIN_TIMEOUT_S}" =~ ^[0-9]+$ ]]; then
            die "HUB_DRAIN_TIMEOUT_S must be a whole number of seconds (got ${HUB_DRAIN_TIMEOUT_S})"
        fi
        if [[ ! "${HUB_DRAIN_POLL_S}" =~ ^[1-9][0-9]*$ ]]; then
            die "HUB_DRAIN_POLL_S must be a positive whole number of seconds (got ${HUB_DRAIN_POLL_S})"
        fi
        count="$(wait_for_drain "${count}")"
    fi
    if ((count > 0)); then
        die "refusing: ${count} running Deployment(s); drain them before upgrading the Hub"
    fi
}

sigterm_celery() {
    run docker compose kill -s SIGTERM worker-deploys worker-probes worker-control beat
}

recreate_app() {
    run docker compose up -d --no-deps web worker-deploys worker-probes worker-control beat
}

smoke_and_probe() {
    run curl -fsS -o /dev/null --max-time 15 "${HUB_SMOKE_URL}"
    run curl -sS -o /dev/null --max-time 15 -X POST "${HUB_LOGIN_URL}"
    run docker compose exec -T web python manage.py shell -c 'from monitor.tasks import collect_all; collect_all()'
}

do_upgrade() {
    refuse_if_running
    local dump_file
    dump_file="${HUB_DUMP_DIR}/hub-$(date -u +%Y%m%dT%H%M%SZ).dump"
    run mkdir -p "${HUB_DUMP_DIR}"
    run pg_dump -Fc -d "${HUB_DB_NAME}" -f "${dump_file}"
    run docker tag "${HUB_IMAGE}" "${HUB_PREVIOUS_IMAGE}"
    run docker compose pull
    run docker compose build
    run docker compose run --rm --no-deps web python manage.py migrate --noinput
    sigterm_celery
    recreate_app
    smoke_and_probe
    echo "hub-upgrade.sh: upgrade complete (previous image kept as ${HUB_PREVIOUS_IMAGE})"
}

do_rollback() {
    refuse_if_running
    run docker tag "${HUB_PREVIOUS_IMAGE}" "${HUB_IMAGE}"
    sigterm_celery
    recreate_app
    smoke_and_probe
    echo "hub-upgrade.sh: rollback restored previous kept image ${HUB_PREVIOUS_IMAGE}"
}

main() {
    local mode
    mode="upgrade"
    local arg
    for arg in "$@"; do
        case "${arg}" in
            -h | --help)
                usage
                exit 0
                ;;
            --rollback)
                mode="rollback"
                ;;
            *)
                die "unknown argument: ${arg} (try --help)"
                ;;
        esac
    done

    echo "hub-upgrade.sh v${SCRIPT_VERSION} DRY_RUN=${DRY_RUN} mode=${mode}"

    case "${mode}" in
        rollback)
            do_rollback
            ;;
        *)
            do_upgrade
            ;;
    esac
}

main "$@"
