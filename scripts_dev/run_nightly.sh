#!/usr/bin/env bash
# Operator-workstation wrapper for `make nightly`.
# Does not run on the Hub host.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

log=$(mktemp)
trap 'rm -f "$log"' EXIT

set +e
make nightly-gates 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
set -e

if (( status != 0 )); then
  # Keep the nightly exit status even if the filer itself fails.
  python scripts_dev/file_nightly_failure.py --exit-code "$status" --log "$log" || true
fi
exit "$status"
