"""Child process entry: load one Deployment pk and call execute.

T2 SIGKILLs this process, not pytest. `--fake` uses deploys.testing's
PipelineTransport so a T1 child needs no SSH and no test module (2.5 panel I2).
"""
from __future__ import annotations

import argparse
import os


def bind_test_database(name=None):
    """Point Django at HUB_TEST_DATABASE so a pytest parent and this child share rows.

    Gated on HUB_TEST_MODE (2.5 panel I2): an env var alone must never repoint
    a prod worker's database.
    """
    from django.conf import settings
    from django.db import connections

    if not getattr(settings, "HUB_TEST_MODE", False):
        return
    name = name or os.environ.get("HUB_TEST_DATABASE")
    if not name:
        return
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
        from deploys.testing import PipelineTransport
        from providers.fakes import FakeDnsProvider, FakeOriginCertIssuer

        kwargs["transport"] = PipelineTransport()
        kwargs["dns"] = FakeDnsProvider()
        kwargs["cert_issuer"] = FakeOriginCertIssuer()
    execute(args.pk, **kwargs)


if __name__ == "__main__":
    main()
