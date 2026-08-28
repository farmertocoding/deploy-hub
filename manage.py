#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

if sys.version_info < (3, 11):
    raise SystemExit(
        f"deploy-hub requires Python >= 3.11 (you have {sys.version.split()[0]})."
    )


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
