"""Versioned catalog entries (§D8). Changed semantics = version bump."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogEntry:
    """One check/fix/rollback triple. `id` is stable; `version` pins semantics."""

    id: str
    version: int
    check: list[str] | list[list[str]]
    fix: list[str] | list[list[str]]
    rollback: list[str] | list[list[str]]
    os_variant: str = "ubuntu"


NTP_CHRONY = CatalogEntry(
    id="ntp-chrony",
    version=1,
    check=["systemctl", "is-active", "chrony"],
    fix=["apt-get", "install", "-y", "chrony"],
    rollback=["systemctl", "disable", "--now", "chrony"],
)

LOG_ROTATION = CatalogEntry(
    id="log-rotation",
    version=2,
    check=["test", "-f", "/etc/logrotate.d/caddy"],
    fix=[
        "install", "-m", "0644",
        "/usr/local/share/hub-catalog/logrotate-caddy",
        "/etc/logrotate.d/caddy",
    ],
    rollback=["rm", "-f", "/etc/logrotate.d/caddy"],
)

DOCKER_DAEMON_JSON = CatalogEntry(
    id="docker-daemon-json",
    version=2,
    check=["test", "-f", "/etc/docker/daemon.json"],
    fix=[
        "install", "-m", "0644",
        "/usr/local/share/hub-catalog/docker-daemon.json",
        "/etc/docker/daemon.json",
    ],
    rollback=["rm", "-f", "/etc/docker/daemon.json"],
)

SSHD_DROPIN = CatalogEntry(
    id="sshd-dropin",
    version=4,
    check=["test", "-f", "/etc/ssh/sshd_config.d/99-hub-hardening.conf"],
    fix=[
        ["sshd", "-t", "-f", "/usr/local/share/hub-catalog/99-hub-hardening.conf"],
        [
            "install", "-m", "0644",
            "/usr/local/share/hub-catalog/99-hub-hardening.conf",
            "/etc/ssh/sshd_config.d/99-hub-hardening.conf",
        ],
    ],
    rollback=["rm", "-f", "/etc/ssh/sshd_config.d/99-hub-hardening.conf"],
)

UFW_POSTURE_HUB = CatalogEntry(
    id="ufw-posture-hub",
    version=1,
    check=["ufw", "status", "verbose"],
    fix=["ufw", "allow", "in", "on", "tailscale0"],
    rollback=["ufw", "delete", "allow", "in", "on", "tailscale0"],
)

UFW_POSTURE_TARGET = CatalogEntry(
    id="ufw-posture-target",
    version=1,
    check=["ufw", "status", "verbose"],
    fix=[
        "ufw", "allow", "proto", "tcp", "from", "173.245.48.0/20",
        "to", "any", "port", "80", "443", "comment", "cloudflare-edge",
    ],
    rollback=[
        "ufw", "delete", "allow", "proto", "tcp", "from", "173.245.48.0/20",
        "to", "any", "port", "80", "443",
    ],
)

UFW_POSTURE_INTAKE = CatalogEntry(
    id="ufw-posture-intake",
    version=1,
    check=["systemctl", "is-active", "cloudflared"],
    fix=["ufw", "allow", "in", "on", "tailscale0"],
    rollback=["ufw", "delete", "allow", "in", "on", "tailscale0"],
)

FAIL2BAN_IGNOREIP = CatalogEntry(
    id="fail2ban-ignoreip",
    version=5,
    check=[
        "grep", "-E",
        "^ignoreip = 127.0.0.1/8 [^[:space:]]+",
        "/etc/fail2ban/jail.local",
    ],
    fix=[
        [
            "install", "-m", "0644",
            "/home/deploy/.hub/jail.local",
            "/etc/fail2ban/jail.local",
        ],
        ["systemctl", "reload", "fail2ban"],
    ],
    rollback=["fail2ban-client", "set", "sshd", "delignoreip", "100.64.1.1"],
)

CADDY = CatalogEntry(
    id="caddy",
    version=1,
    check=["systemctl", "is-active", "caddy"],
    fix=["apt-get", "install", "-y", "caddy"],
    rollback=["systemctl", "disable", "--now", "caddy"],
)

# Hub-side probing handoff (D-036): remove server-watch.sh cron + revoke the
# per-target ntfy publish token. Applied by provision.handoff_hub_probing,
# never silently mutated — change check/fix/rollback ⇒ bump version.
# Runtime also edits the user crontab (named test); this path is the
# /etc/cron.d/server-watch unit that would otherwise keep paging.
SERVER_WATCH_CRON_D = "/etc/cron.d/server-watch"
SERVER_WATCH_HANDOFF = CatalogEntry(
    id="server-watch-handoff",
    version=1,
    check=["test", "!", "-e", SERVER_WATCH_CRON_D],
    fix=["rm", "-f", SERVER_WATCH_CRON_D],
    rollback=["true"],
)

# Caddy's native roller (§C4): roll_size 100MiB, roll_keep 5 — target disk is
# bounded no matter what the Hub does. Validate-first like sshd-dropin; the
# logrotate entry above stays the backstop.
CADDY_LOG_ROLL = CatalogEntry(
    id="caddy-log-roll",
    version=1,
    check=["grep", "-q", "roll_size 100MiB", "/etc/caddy/caddy-log-roll.caddy"],
    fix=[
        [
            "caddy", "validate", "--adapter", "caddyfile", "--config",
            "/usr/local/share/hub-catalog/caddy-log-roll.caddy",
        ],
        [
            "install", "-m", "0644",
            "/usr/local/share/hub-catalog/caddy-log-roll.caddy",
            "/etc/caddy/caddy-log-roll.caddy",
        ],
        ["systemctl", "reload", "caddy"],
    ],
    rollback=[
        ["rm", "-f", "/etc/caddy/caddy-log-roll.caddy"],
        ["systemctl", "reload", "caddy"],
    ],
)

CATALOG: tuple[CatalogEntry, ...] = (
    NTP_CHRONY,
    LOG_ROTATION,
    DOCKER_DAEMON_JSON,
    SSHD_DROPIN,
    UFW_POSTURE_HUB,
    UFW_POSTURE_TARGET,
    UFW_POSTURE_INTAKE,
    FAIL2BAN_IGNOREIP,
    CADDY,
    CADDY_LOG_ROLL,
    SERVER_WATCH_HANDOFF,
)

ENTRIES = {entry.id: entry for entry in CATALOG}
