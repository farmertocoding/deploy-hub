#!/usr/bin/env bash
# update-cloudflare-ufw.sh v2026-08-20
# Canonical: scripts/update-cloudflare-ufw.sh (server-hardening.md)
# Catalog id: ufw-posture-target. Aborts on a bad fetch before touching ufw.
set -euo pipefail

V4_URL="${CLOUDFLARE_IPS_V4_URL:-https://www.cloudflare.com/ips-v4}"
V6_URL="${CLOUDFLARE_IPS_V6_URL:-https://www.cloudflare.com/ips-v6}"
DRY_RUN="${DRY_RUN:-0}"
MIN_V4="${CLOUDFLARE_MIN_V4:-5}"

die() {
    echo "update-cloudflare-ufw.sh: $*" >&2
    exit 1
}

is_cidr() {
    local line="$1"
    [[ "${line}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]] && return 0
    [[ "${line}" =~ ^[0-9a-fA-F:]+/[0-9]+$ ]] && return 0
    return 1
}

fetch_list() {
    local url="$1"
    local body
    if ! body="$(curl -fsS --max-time 30 "${url}")"; then
        die "abort: fetch failed for ${url}"
    fi
    if [[ -z "${body//[[:space:]]/}" ]]; then
        die "abort: fetch from ${url} was empty"
    fi
    printf '%s\n' "${body}"
}

validate_list() {
    local url="$1"
    local min="$2"
    local body="$3"
    local line
    local ok=0
    local bad=0
    while IFS= read -r line || [[ -n "${line}" ]]; do
        [[ -z "${line}" ]] && continue
        if is_cidr "${line}"; then
            ok=$((ok + 1))
        else
            bad=$((bad + 1))
        fi
    done <<<"${body}"
    if [[ "${bad}" -gt 0 || "${ok}" -lt "${min}" ]]; then
        die "abort: fetch from ${url} looks invalid (${ok} CIDRs, ${bad} bad lines; need >= ${min})"
    fi
}

apply_ranges() {
    local proto="$1"
    local body="$2"
    local line
    while IFS= read -r line || [[ -n "${line}" ]]; do
        [[ -z "${line}" ]] && continue
        if [[ "${DRY_RUN}" == "1" ]]; then
            printf 'DRY_RUN: ufw allow proto tcp from %s to any port 80,443 comment cloudflare-edge\n' "${line}"
            continue
        fi
        ufw allow proto tcp from "${line}" to any port 80 comment "cloudflare-edge-${proto}" >/dev/null
        ufw allow proto tcp from "${line}" to any port 443 comment "cloudflare-edge-${proto}" >/dev/null
    done <<<"${body}"
}

main() {
    local v4 v6
    v4="$(fetch_list "${V4_URL}")"
    validate_list "${V4_URL}" "${MIN_V4}" "${v4}"
    v6="$(fetch_list "${V6_URL}")"
    validate_list "${V6_URL}" 1 "${v6}"

    apply_ranges v4 "${v4}"
    apply_ranges v6 "${v6}"
    echo "update-cloudflare-ufw.sh: cloudflare ufw ranges refreshed"
}

main "$@"
