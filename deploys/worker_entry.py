"""Child process entry: load one Deployment pk and call execute.

T2 SIGKILLs this process, not pytest. `--fake` uses PipelineTransport so a
T1 child needs no SSH.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def bind_test_database(name=None):
    """Point Django at HUB_TEST_DATABASE so a pytest parent and this child share rows."""
    name = name or os.environ.get("HUB_TEST_DATABASE")
    if not name:
        return
    from django.conf import settings
    from django.db import connections

    settings.DATABASES["default"]["NAME"] = str(name)
    connections.databases["default"]["NAME"] = str(name)
    connections.close_all()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one deployment as a worker child.")
    parser.add_argument("pk", type=int)
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Use PipelineTransport + FakeDnsProvider (no SSH).",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
    import django

    django.setup()
    bind_test_database()

    from deploys.pipeline import execute

    kwargs = {}
    if args.fake:
        tests_dir = Path(__file__).resolve().parent.parent / "tests"
        if str(tests_dir) not in sys.path:
            sys.path.insert(0, str(tests_dir))
        from pipeline_fakes import PipelineTransport

        from providers.fakes import FakeDnsProvider

        kwargs["transport"] = PipelineTransport()
        kwargs["dns"] = FakeDnsProvider()
    execute(args.pk, **kwargs)


if __name__ == "__main__":
    main()
