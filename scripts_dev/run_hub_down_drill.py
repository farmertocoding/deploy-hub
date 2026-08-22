#!/usr/bin/env python3
"""Exercise the hub-down drill body. SKIPPED (no live site) is exit 0."""
import os
import sys
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
    django.setup()
    from monitor.drills import nightly_exit_code, run_hub_down_drill

    run = run_hub_down_drill()
    return nightly_exit_code(run)


if __name__ == "__main__":
    raise SystemExit(main())
