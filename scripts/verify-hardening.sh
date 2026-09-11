#!/usr/bin/env bash
# verify-hardening.sh v2026-08-22
# Canonical: scripts/verify-hardening.sh (server-hardening.md)
# Read-only drift check. Maps to catalog check argv (Task 5 ids).
set -euo pipefail

PROFILE="${PROFILE:-}"
HUB_MESH_IP="${HUB_MESH_IP:-}"
TAILNET_SLASH10="100.64.0.0/10"
SSHD_DROPIN="/etc/ssh/sshd_config.d/99-hub-hardening.conf"
JAIL_LOCAL="/etc/fail2ban/jail.local"
failed=0

fail() {
    echo "FAIL: $*" >&2
    failed=1
}

ok() {
    echo "ok: $*"
}

require_profile() {
    case "${PROFILE}" in
        hub | target | intake) ;;
        *)
            echo "verify-hardening.sh: PROFILE must be hub, target, or intake" >&2
            exit 1
            ;;
    esac
}

main() {
    require_profile
    echo "verify-hardening.sh PROFILE=${PROFILE}"

    if sshd -t 2>/dev/null; then
        ok "sshd -t"
    else
        fail "sshd -t"
    fi

    if [[ -f "${SSHD_DROPIN}" ]] && grep -q 'PasswordAuthentication no' "${SSHD_DROPIN}"; then
        ok "sshd drop-in ${SSHD_DROPIN}"
    else
        fail "sshd drop-in missing or password auth still allowed"
    fi

    if [[ -f "${JAIL_LOCAL}" ]]; then
        if grep -E '^[[:space:]]*ignoreip' "${JAIL_LOCAL}" | grep -q "${TAILNET_SLASH10}"; then
            fail "fail2ban ignoreip still whitelists ${TAILNET_SLASH10}"
        elif [[ -n "${HUB_MESH_IP}" ]] && grep -E '^[[:space:]]*ignoreip' "${JAIL_LOCAL}" | grep -q "${HUB_MESH_IP}"; then
            ok "fail2ban ignoreip is HUB_MESH_IP ${HUB_MESH_IP}"
        elif [[ -n "${HUB_MESH_IP}" ]]; then
            fail "fail2ban ignoreip missing HUB_MESH_IP ${HUB_MESH_IP}"
        else
            ok "fail2ban ignoreip is not the tailnet /10"
        fi
    else
        fail "missing ${JAIL_LOCAL}"
    fi

    if command -v chronyc >/dev/null 2>&1 || systemctl is-active --quiet chrony 2>/dev/null; then
        ok "chrony"
    else
        fail "chrony inactive"
    fi

    if [[ -f /etc/docker/daemon.json ]] &&
        grep -q '"live-restore"[[:space:]]*:[[:space:]]*true' /etc/docker/daemon.json &&
        grep -q '"no-new-privileges"[[:space:]]*:[[:space:]]*true' /etc/docker/daemon.json; then
        ok "docker daemon.json"
    else
        fail "missing /etc/docker/daemon.json live-restore/no-new-privileges"
    fi

    # A `type dummy` tailscale0 is a manufactured standin, not a mesh: it
    # would make the ufw grep below (and any tailscale0-shaped posture) a
    # false green on a host that never joined a tailnet.
    if ip -d link show tailscale0 2>/dev/null | grep -qw dummy; then
        fail "tailscale0 exists but is a dummy interface, not a mesh"
    fi

    case "${PROFILE}" in
        hub | intake)
            if ufw status verbose 2>/dev/null | grep -q tailscale0; then
                ok "${PROFILE} ufw mentions tailscale0"
            else
                fail "${PROFILE} ufw posture (tailscale0) not observed"
            fi
            ;;
        target)
            if ufw status verbose 2>/dev/null | grep -qi cloudflare; then
                ok "target ufw mentions cloudflare"
            else
                fail "target ufw cloudflare posture not observed"
            fi
            ;;
    esac

    if [[ "${failed}" -ne 0 ]]; then
        echo "verify-hardening.sh: FAIL" >&2
        exit 1
    fi
    echo "verify-hardening.sh: PASS"
}

main "$@"
