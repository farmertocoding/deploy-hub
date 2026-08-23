"""T1 Fake partner reaper: plant orphan, containers gone, routes detached.

Distinct from Multipass hub-t3- and AWS purpose=test. Weekly drill writes
CheckRun.Kind.PARTNER_REAPER. Do not fold into drill-reaper-weekly.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from core.transport import FakeTransport

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)
_IMPORT_MULTIPASS = re.compile(r"\bmultipass\b")


@pytest.mark.req("PART-KILL-SWITCH")
def test_partner_reaper_plants_orphan_and_cleans():
    """Plant Partner gone / kill-switched / quota-expired → stop + detach.

    What would make this fail: leaving the Fake container running, leaving
    the Caddy route, or reaping through Multipass/AWS instead of Fake Transport.
    """
    from monitor.partner_reaper import plant_orphan, reap_orphans

    transport = FakeTransport()
    for reason in ("partner-gone", "kill-switched", "quota-expired"):
        planted = plant_orphan(transport=transport, reason=reason)
        assert planted["container"]
        assert planted["route_id"]
        assert planted["reason"] == reason
        runs_before = [c[1] for c in transport.calls if c[0] == "run"]
        assert any(
            argv[:3] == ["docker", "run", "-d"] or argv[:2] == ["docker", "run"]
            for argv in runs_before
        ), runs_before
        reap_orphans(transport=transport)
        runs = [c[1] for c in transport.calls if c[0] == "run"]
        name = planted["container"]
        route_id = planted["route_id"]
        assert any(argv[:3] == ["docker", "stop", name] for argv in runs), runs
        assert any(
            "DELETE" in argv and route_id in " ".join(argv) for argv in runs
        ), runs
        transport.calls.clear()


@pytest.mark.req("PART-KILL-SWITCH")
def test_partner_reaper_writes_checkrun_kind_partner_reaper():
    """Weekly Fake drill plants an orphan, asserts gone, writes PARTNER_REAPER.

    What would make this fail: writing Kind.REAPER / AWS_REAPER, skipping the
    CheckRun, or adding partner_reaper to DRILL_PERIODS[REAPER].
    """
    from core.models import CheckRun
    from monitor.drills import DRILL_PERIODS, run_partner_reaper_drill

    assert CheckRun.Kind.PARTNER_REAPER not in DRILL_PERIODS
    assert CheckRun.Kind.INTAKE_POLL not in DRILL_PERIODS
    transport = FakeTransport()
    run = run_partner_reaper_drill(transport=transport)
    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.kind == CheckRun.Kind.PARTNER_REAPER
    assert stored.kind != CheckRun.Kind.REAPER
    assert stored.kind != CheckRun.Kind.AWS_REAPER
    assert stored.status == CheckRun.Status.SUCCEEDED
    assert stored.results["schema_version"] == 1
    assert stored.results.get("gone") is True
    name = stored.results["planted_container"]
    runs = [c[1] for c in transport.calls if c[0] == "run"]
    assert any(argv[:3] == ["docker", "stop", name] for argv in runs), runs


def test_multipass_and_aws_reapers_untouched():
    """Multipass stays hub-t3-; AWS stays purpose=test; partner reaper is Fake.

    What would make this fail: boto3 in partner_reaper or reaper.py, folding
    partner into drill-reaper-weekly, or claiming HARNESS-REAPER-TEST-PLANE.
    """
    from django.conf import settings

    from conformance.check import collect_markers
    from core.models import CheckRun
    from monitor.drills import DRILL_PERIODS
    from monitor.reaper import NAME_PREFIX

    reaper_src = (REPO / "monitor" / "reaper.py").read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(reaper_src) is None
    assert "boto3" not in reaper_src
    assert NAME_PREFIX == "hub-t3-"
    assert 'NAME_PREFIX = "hub-t3-"' in reaper_src

    cloud_src = (REPO / "monitor" / "cloud_reaper.py").read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(cloud_src) is None
    assert "purpose" in cloud_src and "test" in cloud_src

    partner_src = (REPO / "monitor" / "partner_reaper.py").read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(partner_src) is None
    assert "boto3" not in partner_src
    assert "botocore" not in partner_src
    assert "moto" not in partner_src
    assert _IMPORT_MULTIPASS.search(partner_src) is None
    assert "hub-t3-" not in partner_src
    assert "purpose=test" not in partner_src.replace(" ", "")

    drills_src = (REPO / "monitor" / "drills.py").read_text(encoding="utf-8")
    assert "run_partner_reaper_drill" in drills_src
    assert CheckRun.Kind.PARTNER_REAPER not in DRILL_PERIODS
    beat = settings.CELERY_BEAT_SCHEDULE["drill-reaper-weekly"]
    assert beat["task"] == "monitor.tasks.run_reaper_drill"
    assert "partner_reaper" not in beat["task"]

    nodeids = collect_markers(REPO).get("HARNESS-REAPER-TEST-PLANE") or []
    claimed = [n for n in nodeids if "partner_reaper" in n]
    assert claimed == []

    for rel in (
        "monitor/partner_reaper.py",
        "tests/test_partner_reaper.py",
    ):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert _IMPORT_BOTO.search(text) is None, rel
