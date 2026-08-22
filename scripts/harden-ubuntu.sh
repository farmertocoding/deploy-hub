#!/usr/bin/env bash
# harden-ubuntu.sh v2026-08-22
# Canonical: scripts/harden-ubuntu.sh (server-hardening.md)
# Pre-Hub interim of catalog ids: ntp-chrony, log-rotation, docker-daemon-json,
# sshd-dropin, ufw-posture-hub, ufw-posture-target, ufw-posture-intake,
# fail2ban-ignoreip, caddy.
#
# Test-only env (T3 Multipass — never set on a real host):
#   HUB_T3_ALLOW_NO_MESH=1 / HUB_T3_UFW_ONLY=1
#     Skip the mesh-before-firewall refuse so ufw+fail2ban can still be
#     enabled on a throwaway VM with no tailnet. HUB_MESH_IP is still
#     required (singular IPv4, never 100.64.0.0/10). This path does NOT
#     prove HARD-V2; the default path still fail-closes when the env is unset.
#   HUB_T3_SSH_FROM=<ipv4>
#     Extra ufw allow of tcp/22 from that address so pytest can SSH after
#     ufw enable (Multipass is not on tailscale0).
set -euo pipefail

SCRIPT_VERSION="2026-08-22"
STAMP_DIR="${HUB_STAMP_DIR:-/var/lib/hub-harden}"
PROFILE="${PROFILE:-}"
DRY_RUN="${DRY_RUN:-0}"
HUB_MESH_IP="${HUB_MESH_IP:-}"
HUB_CONFIRM_LOCAL="${HUB_CONFIRM_LOCAL:-0}"
HUB_T3_ALLOW_NO_MESH="${HUB_T3_ALLOW_NO_MESH:-0}"
HUB_T3_UFW_ONLY="${HUB_T3_UFW_ONLY:-0}"
HUB_T3_SSH_FROM="${HUB_T3_SSH_FROM:-}"

SSHD_DROPIN="${HUB_SSHD_DROPIN:-/etc/ssh/sshd_config.d/99-hub-hardening.conf}"
JAIL_LOCAL="${HUB_JAIL_LOCAL:-/etc/fail2ban/jail.local}"
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

session_peer_ip() {
    # SSH_CONNECTION is "client_ip client_port server_ip server_port".
    # sudo env_reset drops it; SSH_CLIENT ("client_ip client_port server_port")
    # survives only if sudoers env_keep lists it.
    if [[ -n "${SSH_CONNECTION:-}" ]]; then
        printf '%s\n' "${SSH_CONNECTION%% *}"
        return 0
    fi
    if [[ -n "${SSH_CLIENT:-}" ]]; then
        printf '%s\n' "${SSH_CLIENT%% *}"
        return 0
    fi
    return 1
}

session_rides_mesh() {
    local peer
    if peer="$(session_peer_ip)"; then
        in_tailnet_cgnat "${peer}"
        return $?
    fi
    # Unset SSH_* is sudo env_reset *or* a real console. Do not treat silence
    # as a verified second path — public SSH + sudo would lock the operator out.
    [[ "${HUB_CONFIRM_LOCAL}" == "1" ]]
}

t3_allow_no_mesh() {
    [[ "${HUB_T3_ALLOW_NO_MESH}" == "1" || "${HUB_T3_UFW_ONLY}" == "1" ]]
}

ensure_t3_tailscale0_standin() {
    # Dummy iface so `ufw allow in on tailscale0` can still be applied.
    # Not a mesh; HARD-V2 is not proven on this path.
    if ip link show tailscale0 >/dev/null 2>&1; then
        return 0
    fi
    if command -v modprobe >/dev/null 2>&1; then
        run modprobe dummy || true
    fi
    run ip link add tailscale0 type dummy || true
    run ip link set tailscale0 up || true
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
    local content dest snippet trial
    content="$(sshd_dropin_content | sed 's/[[:space:]]*$//')"
    dest="${SSHD_DROPIN}"
    if [[ "${DRY_RUN}" == "1" ]]; then
        # Validate a temp drop-in before touching the live path (R2).
        printf 'DRY_RUN: sshd -t -f <temp-dropin>\n'
        printf 'DRY_RUN: write %s\n' "${dest}"
        printf '%s\n' "${content}"
        return 0
    fi
    if [[ -f "${dest}" ]] && printf '%s\n' "${content}" | cmp -s - "${dest}"; then
        run sshd -t
        return 0
    fi
    snippet="$(mktemp "${TMPDIR:-/tmp}/hub-sshd-dropin.XXXXXX")"
    trial="$(mktemp "${TMPDIR:-/tmp}/hub-sshd-trial.XXXXXX")"
    printf '%s\n' "${content}" >"${snippet}"
    if [[ -f /etc/ssh/sshd_config ]]; then
        printf 'Include /etc/ssh/sshd_config\n' >"${trial}"
        cat "${snippet}" >>"${trial}"
    else
        cat "${snippet}" >"${trial}"
    fi
    if ! sshd -t -f "${trial}"; then
        rm -f "${snippet}" "${trial}"
        die "sshd -t failed; live drop-in ${dest} left untouched"
    fi
    rm -f "${trial}"
    local dir
    dir="$(dirname "${dest}")"
    mkdir -p "${dir}"
    install -m 0644 "${snippet}" "${dest}"
    rm -f "${snippet}"
    run systemctl reload ssh
}

apply_fail2ban() {
    local changed=0
    ensure_pkg fail2ban
    if ! write_file "${JAIL_LOCAL}" "$(jail_local_content | sed 's/[[:space:]]*$//')"; then
        changed=1
    fi
    if [[ "${DRY_RUN}" == "1" ]]; then
        # Install starts fail2ban before jail.local exists; reload is required
        # so the new ignoreip is loaded (HARD-R3).
        printf 'DRY_RUN: systemctl reload fail2ban\n'
        return 0
    fi
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet fail2ban 2>/dev/null; then
        if [[ "${changed}" == "1" ]]; then
            run systemctl reload fail2ban
        fi
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
    if t3_allow_no_mesh && ! ip link show tailscale0 >/dev/null 2>&1; then
        echo "harden-ubuntu.sh: no tailscale0; T3 UFW_ONLY continues (HARD-V2 not proven)"
    else
        run ufw allow in on tailscale0 comment 'tailscale mesh'
    fi
    run ufw allow proto tcp from 173.245.48.0/20 to any port 80 comment 'cloudflare-edge'
    run ufw allow proto tcp from 173.245.48.0/20 to any port 443 comment 'cloudflare-edge'
    if [[ -n "${HUB_T3_SSH_FROM}" ]]; then
        is_ipv4 "${HUB_T3_SSH_FROM}" || die "HUB_T3_SSH_FROM must be a single IPv4"
        run ufw allow proto tcp from "${HUB_T3_SSH_FROM}" to any port 22 comment 't3-multipass-ssh'
    fi
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
        if t3_allow_no_mesh; then
            echo "harden-ubuntu.sh: HUB_T3_UFW_ONLY/HUB_T3_ALLOW_NO_MESH set; skipping mesh-before-firewall (does not prove HARD-V2)"
            if [[ -n "${HUB_T3_SSH_FROM}" ]]; then
                is_ipv4 "${HUB_T3_SSH_FROM}" || die "HUB_T3_SSH_FROM must be a single IPv4"
            fi
            ensure_t3_tailscale0_standin
        else
            die "refusing tailscale0-only firewall: mesh is not up or this session does not ride it (V2)"
        fi
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
