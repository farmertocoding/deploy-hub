import os
import sys

# Fail loud with the FIX in the message, not a tomllib traceback three modules deep.
# (Round-3 finding, found by Joseph running the suite on a 3.10 venv, 2026-08-09.)
if sys.version_info < (3, 11):
    raise SystemExit(
        f"deploy-hub requires Python >= 3.11 (you have {sys.version.split()[0]}: "
        f"{sys.executable}). Recreate the venv: rm -rf .venv && "
        f"python3.12 -m venv .venv && source .venv/bin/activate && "
        f"pip install -r requirements-dev.txt"
    )

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
django.setup()
