#!/usr/bin/env bash
# server-watch.sh v2026-08-20
# Canonical: scripts/server-watch.sh (server-hardening.md)
# Interim fleet alerting (review3 §V8/§M3): a distinct per-server ntfy token.
set -euo pipefail

NTFY_URL="${NTFY_URL:-}"
NTFY_TOKEN="${NTFY_TOKEN:-}"
NTFY_TOPIC="${NTFY_TOPIC:-}"
HOST="$(hostname -s 2>/dev/null || hostname)"

die() {
    echo "server-watch.sh: $*" >&2
    exit 1
}

# Bare topic names are bearer tokens (M3). A publish without a per-server token
# would let any host that learns the topic spoof or flood the pager.
if [[ -z "${NTFY_TOKEN}" ]]; then
    die "NTFY_TOKEN is required (per-server publish token; refusing a bare topic)"
fi
if [[ -z "${NTFY_URL}" && -z "${NTFY_TOPIC}" ]]; then
    die "set NTFY_URL or NTFY_TOPIC"
fi
if [[ -z "${NTFY_URL}" ]]; then
    NTFY_URL="https://ntfy.sh/${NTFY_TOPIC}"
fi

status="ok"
body="${HOST} heartbeat"
if ! command -v systemctl >/dev/null 2>&1; then
    status="degraded"
    body="${HOST} systemctl missing"
elif ! systemctl is-system-running >/dev/null 2>&1; then
    status="degraded"
    body="${HOST} systemd is not running"
fi

priority="default"
title="[HUB P3] ${HOST} watch"
if [[ "${status}" != "ok" ]]; then
    priority="high"
    title="[HUB P2] ${HOST} watch ${status}"
fi

curl -fsS --max-time 15 \
    -H "Authorization: Bearer ${NTFY_TOKEN}" \
    -H "Priority: ${priority}" \
    -H "Title: ${title}" \
    -d "${body}" \
    "${NTFY_URL}" >/dev/null

echo "server-watch.sh: published ${status} for ${HOST}"
