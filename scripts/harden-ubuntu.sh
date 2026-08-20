#!/usr/bin/env bash
# harden-ubuntu.sh v2026-08-20
# Canonical: scripts/harden-ubuntu.sh (server-hardening.md)
# Pre-Hub interim of catalog ids: ntp-chrony, log-rotation, docker-daemon-json,
# sshd-dropin, ufw-posture-hub, ufw-posture-target, ufw-posture-intake,
# fail2ban-ignoreip, caddy.
set -euo pipefail

SCRIPT_VERSION="2026-08-20"
STAMP_DIR="${HUB_STAMP_DIR:-/var/lib/hub-harden}"
PROFILE="${PROFILE:-}"
DRY_RUN="${DRY_RUN:-0}"
HUB_MESH_IP="${HUB_MESH_IP:-}"

SSHD_DROPIN="/etc/ssh/sshd_config.d/99-hub-hardening.conf"
JAIL_LOCAL="/etc/fail2ban/jail.local"
SYSCTL_DROPIN="/etc/sysctl.d/99-hub-hardening.conf"
DOCKER_DAEMON="/etc/docker/daemon.json"
LOGROTATE_CADDY="/etc/logrotate.d/caddy"

die() {
    echo "harden-ubuntu.sh: $*" >&2
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

stamp_path() {
    printf '%s/%s.done' "${STAMP_DIR}" "$1"
}

is_stamped() {
    [[ -f "$(stamp_path "$1")" ]]
}

mark_stamped() {
    if [[ "${DRY_RUN}" == "1" ]]; then
        return 0
    fi
    mkdir -p "${STAMP_DIR}"
    touch "$(stamp_path "$1")"
}

write_file() {
    local path="$1"
    local content="$2"
    if [[ "${DRY_RUN}" == "1" ]]; then
        printf 'DRY_RUN: write %s\n' "${path}"
        printf '%s\n' "${content}"
        return 0
    fi
    if [[ -f "${path}" ]] && printf '%s\n' "${content}" | cmp -s - "${path}"; then
        return 0
    fi
    local dir
    dir="$(dirname "${path}")"
    mkdir -p "${dir}"
    local tmp
    tmp="$(mktemp "${dir}/.hub-harden.XXXXXX")"
    printf '%s\n' "${content}" >"${tmp}"
    install -m 0644 "${tmp}" "${path}"
    rm -f "${tmp}"
    return 1
}

pkg_present() {
    local name="$1"
    if is_stamped "pkg-${name}"; then
        return 0
    fi
    if command -v dpkg >/dev/null 2>&1 && dpkg -s "${name}" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

ensure_pkg() {
    local name="$1"
    if pkg_present "${name}"; then
        return 0
    fi
    run apt-get install -y "${name}"
    mark_stamped "pkg-${name}"
}

has_authorized_keys() {
    local candidates=()
    local f
    if [[ -n "${HOME:-}" ]]; then
        candidates+=("${HOME}/.ssh/authorized_keys")
    fi
    candidates+=("/root/.ssh/authorized_keys")
    if [[ -n "${SUDO_USER:-}" ]]; then
        candidates+=("/home/${SUDO_USER}/.ssh/authorized_keys")
    fi
    for f in "${candidates[@]}"; do
        if [[ -s "${f}" ]]; then
            return 0
        fi
    done
    return 1
}

is_ipv4() {
    local ip="$1"
    [[ "${ip}" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] || return 1
    local o
    IFS=. read -r -a o <<<"${ip}"
    local n
    for n in "${o[@]}"; do
        ((n >= 0 && n <= 255)) || return 1
    done
    return 0
}

in_tailnet_cgnat() {
    local ip="$1"
    is_ipv4 "${ip}" || return 1
    local a b
    IFS=. read -r a b _ _ <<<"${ip}"
    [[ "${a}" == "100" && "${b}" -ge 64 && "${b}" -le 127 ]]
}

mesh_is_up() {
    tailscale status >/dev/null 2>&1
}

session_rides_mesh() {
    # Local console (no SSH_CONNECTION) is the verified second path.
    if [[ -z "${SSH_CONNECTION:-}" ]]; then
        return 0
    fi
    local client="${SSH_CONNECTION%% *}"
    in_tailnet_cgnat "${client}"
}

require_profile() {
    case "${PROFILE}" in
        hub | target | intake) ;;
        *)
            die "PROFILE must be hub, target, or intake (got ${PROFILE:-empty})"
            ;;
    esac
}

require_hub_mesh_ip() {
    [[ -n "${HUB_MESH_IP}" ]] || die "HUB_MESH_IP is required (the Hub's mesh IP, singular)"
    if [[ "${HUB_MESH_IP}" == */* ]]; then
        die "HUB_MESH_IP must be a single IP, never a CIDR (refusing ${HUB_MESH_IP})"
    fi
    is_ipv4 "${HUB_MESH_IP}" || die "HUB_MESH_IP must be an IPv4 address (got ${HUB_MESH_IP})"
}

sshd_dropin_content() {
    cat <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 3
EOF
}

jail_local_content() {
    cat <<EOF
[sshd]
enabled = true
maxretry = 4
findtime = 10m
bantime = 1h
ignoreip = 127.0.0.1/8 ${HUB_MESH_IP}
# ignoreip = 127.0.0.1/8 100.64.0.0/10   # only after tailnet ACLs restrict target↔target
EOF
}

sysctl_content() {
    cat <<'EOF'
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
EOF
}

daemon_json_content() {
    cat <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "3"
  },
  "live-restore": true,
  "no-new-privileges": true
}
EOF
}

logrotate_caddy_content() {
    cat <<'EOF'
/var/log/caddy/*.log {
    weekly
    rotate 8
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
EOF
}

apply_sshd() {
    local changed=0
    if ! write_file "${SSHD_DROPIN}" "$(sshd_dropin_content | sed 's/[[:space:]]*$//')"; then
        changed=1
    fi
    # sshd -t FIRST: a typo + reload = locked out (R2).
    run sshd -t
    if [[ "${changed}" == "1" ]]; then
        run systemctl reload ssh
    fi
}

apply_fail2ban() {
    ensure_pkg fail2ban
    write_file "${JAIL_LOCAL}" "$(jail_local_content | sed 's/[[:space:]]*$//')" || true
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet fail2ban 2>/dev/null; then
        return 0
    fi
    run systemctl enable --now fail2ban
}

ufw_already_active() {
    if is_stamped ufw-enable; then
        return 0
    fi
    ufw status 2>/dev/null | grep -q 'Status: active'
}

enable_ufw() {
    if ufw_already_active; then
        return 0
    fi
    run ufw --force enable
    mark_stamped ufw-enable
}

apply_ufw_hub_or_intake() {
    run ufw default deny incoming
    run ufw default allow outgoing
    run ufw allow in on tailscale0 comment 'tailscale mesh'
    enable_ufw
}

apply_ufw_target() {
    run ufw default deny incoming
    run ufw default allow outgoing
    run ufw allow in on tailscale0 comment 'tailscale mesh'
    run ufw allow proto tcp from 173.245.48.0/20 to any port 80 comment 'cloudflare-edge'
    run ufw allow proto tcp from 173.245.48.0/20 to any port 443 comment 'cloudflare-edge'
    enable_ufw
}

main() {
    require_profile
    require_hub_mesh_ip

    echo "harden-ubuntu.sh v${SCRIPT_VERSION} PROFILE=${PROFILE} DRY_RUN=${DRY_RUN}"

    if ! has_authorized_keys; then
        die "refusing to disable password auth: no authorized_keys file exists"
    fi

    if ! mesh_is_up || ! session_rides_mesh; then
        die "refusing tailscale0-only firewall: mesh is not up or this session does not ride it (V2)"
    fi

    ensure_pkg unattended-upgrades
    ensure_pkg chrony
    ensure_pkg ufw

    apply_sshd
    apply_fail2ban

    if [[ "${DRY_RUN}" == "1" ]]; then
        printf 'DRY_RUN:'
        printf ' %q' tee /etc/apt/apt.conf.d/20auto-upgrades
        printf '\n'
    else
        if [[ ! -f /etc/apt/apt.conf.d/20auto-upgrades ]]; then
            printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
                >/etc/apt/apt.conf.d/20auto-upgrades
        fi
    fi

    write_file "${SYSCTL_DROPIN}" "$(sysctl_content | sed 's/[[:space:]]*$//')" || true
    if command -v sysctl >/dev/null 2>&1; then
        if [[ "${DRY_RUN}" == "1" ]] || ! is_stamped sysctl; then
            run sysctl --system
            mark_stamped sysctl
        fi
    fi

    if command -v systemctl >/dev/null 2>&1 && ! systemctl is-active --quiet chrony 2>/dev/null; then
        run systemctl enable --now chrony
    fi

    if [[ ! -f "${DOCKER_DAEMON}" ]]; then
        write_file "${DOCKER_DAEMON}" "$(daemon_json_content | sed 's/[[:space:]]*$//')" || true
    fi

    case "${PROFILE}" in
        hub | intake)
            apply_ufw_hub_or_intake
            ;;
        target)
            apply_ufw_target
            ensure_pkg caddy || true
            if command -v caddy >/dev/null 2>&1 || is_stamped pkg-caddy; then
                if command -v systemctl >/dev/null 2>&1 && ! systemctl is-active --quiet caddy 2>/dev/null; then
                    run systemctl enable --now caddy
                fi
            fi
            write_file "${LOGROTATE_CADDY}" "$(logrotate_caddy_content | sed 's/[[:space:]]*$//')" || true
            ;;
    esac

    echo "harden-ubuntu.sh: done"
}

main "$@"
