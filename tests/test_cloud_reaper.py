"""Cloud reaper on the CloudProvider port (AWS-TEST-PLANE).

After the D-066 wall, list_tagged_instances({purpose: test}) then
terminate_instance. No-op when HUB_TEST_MODE is False. Weekly drill plants
a FakeCloudProvider purpose=test instance, asserts gone, writes
CheckRun.Kind.AWS_REAPER. Multipass reaper stays hub-t3- and boto3-free.
HARNESS-REAPER-TEST-PLANE does not cover AWS. tests/ do not import boto3.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from django.test import override_settings

from providers.fakes import FakeCloudProvider

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
ACCOUNT = "123456789012"
REGION = "us-east-1"
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)
AWS_WALL = {
    "HUB_TEST_MODE": True,
    "HUB_TEST_AWS_ACCOUNT_IDS": [ACCOUNT],
    "HUB_TEST_AWS_REGIONS": [REGION],
}


class RecordingCloud(FakeCloudProvider):
    """FakeCloudProvider plus a call log."""

    _MUTATING = frozenset(
        {"create_instance", "terminate_instance", "ensure_ingress_rules"}
    )

    def __init__(self):
        super().__init__()
        self.calls = []

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def create_instance(self, spec):
        self.calls.append(("create_instance", spec))
        return super().create_instance(spec)

    def terminate_instance(self, instance_id):
        self.calls.append(("terminate_instance", instance_id))
        return super().terminate_instance(instance_id)

    def list_tagged_instances(self, tags):
        self.calls.append(("list_tagged_instances", tags))
        return super().list_tagged_instances(tags)


@pytest.mark.req("AWS-TEST-PLANE")
def test_cloud_reaper_respects_allowlist_and_purpose_test():
    """Only purpose=test instances die, and only after the D-066 wall.

    What would make this fail: terminating purpose=prod leftovers, or
    skipping assert_test_aws so an off-allowlist account still reaps.
    """
    from core.test_mode import TestModeError
    from monitor.cloud_reaper import reap_cloud_test_plane

    provider = RecordingCloud()
    test_inst = provider.create_instance(
        {"name": "hub-aws-test", "tags": {"purpose": "test", "Name": "hub-aws-test"}}
    )
    prod_inst = provider.create_instance(
        {"name": "hub-aws-prod", "tags": {"purpose": "prod", "Name": "hub-aws-prod"}}
    )
    with override_settings(**AWS_WALL):
        reap_cloud_test_plane(
            provider, account_id=ACCOUNT, region_name=REGION,
        )
    assert test_inst["id"] not in provider.instances
    assert prod_inst["id"] in provider.instances
    assert any(
        c[0] == "list_tagged_instances" and c[1] == {"purpose": "test"}
        for c in provider.calls
    )

    blocked = RecordingCloud()
    leftover = blocked.create_instance(
        {"name": "hub-aws-off", "tags": {"purpose": "test", "Name": "hub-aws-off"}}
    )
    with override_settings(
        HUB_TEST_MODE=True,
        HUB_TEST_AWS_ACCOUNT_IDS=["999999999999"],
        HUB_TEST_AWS_REGIONS=[REGION],
    ):
        with pytest.raises(TestModeError):
            reap_cloud_test_plane(
                blocked, account_id=ACCOUNT, region_name=REGION,
            )
    assert leftover["id"] in blocked.instances
    assert not any(c[0] == "terminate_instance" for c in blocked.calls)


@pytest.mark.req("AWS-TEST-PLANE")
def test_cloud_reaper_noop_when_hub_test_mode_false():
    """HUB_TEST_MODE=False is a no-op: no list, no terminate, no TestModeError.

    What would make this fail: calling terminate_instance (or assert_test_aws
    with purpose=test, which refuses outside test mode) when the flag is off.
    """
    from core.test_mode import TestModeError
    from monitor.cloud_reaper import reap_cloud_test_plane

    provider = RecordingCloud()
    planted = provider.create_instance(
        {"name": "hub-aws-live", "tags": {"purpose": "test", "Name": "hub-aws-live"}}
    )
    with override_settings(HUB_TEST_MODE=False):
        reap_cloud_test_plane(
            provider, account_id=ACCOUNT, region_name=REGION,
        )
    assert planted["id"] in provider.instances
    assert not any(c[0] == "terminate_instance" for c in provider.calls)
    assert not any(c[0] == "list_tagged_instances" for c in provider.calls)
    # Calling the reaper must not raise the purpose=test-outside-mode refusal.
    with override_settings(HUB_TEST_MODE=False):
        try:
            reap_cloud_test_plane(
                provider, account_id=ACCOUNT, region_name=REGION,
            )
        except TestModeError:
            pytest.fail("HUB_TEST_MODE=False must no-op, not raise TestModeError")


@pytest.mark.req("AWS-TEST-PLANE")
def test_cloud_reaper_writes_checkrun_kind_aws_reaper():
    """The cloud reaper persists CheckRun.Kind.AWS_REAPER.

    What would make this fail: writing Kind.REAPER (Multipass) or skipping
    the CheckRun so weekly AWS leftovers have no drill row.
    """
    from core.models import CheckRun
    from monitor.cloud_reaper import reap_cloud_test_plane

    provider = RecordingCloud()
    provider.create_instance(
        {"name": "hub-aws-check", "tags": {"purpose": "test"}}
    )
    with override_settings(**AWS_WALL):
        run = reap_cloud_test_plane(
            provider, account_id=ACCOUNT, region_name=REGION,
        )
    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.kind == CheckRun.Kind.AWS_REAPER
    assert stored.kind != CheckRun.Kind.REAPER
    assert stored.status == CheckRun.Status.SUCCEEDED
    assert stored.results["schema_version"] == 1


def test_cloud_reaper_does_not_import_boto3():
    """monitor/cloud_reaper.py takes a CloudProvider port; boto3 stays in providers/.

    What would make this fail: importing boto3/botocore/moto in the reaper
    or in this test module.
    """
    for rel in (
        "monitor/cloud_reaper.py",
        "tests/test_cloud_reaper.py",
        "tests/test_aws_terminate.py",
    ):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert _IMPORT_BOTO.search(text) is None, rel


def test_multipass_reaper_unchanged_no_boto3():
    """monitor/reaper.py stays Multipass hub-t3- prefix-only; no boto3.

    What would make this fail: adding boto3 to the Multipass reaper, or
    widening NAME_PREFIX so production names become reaper-eligible.
    """
    src = (REPO / "monitor" / "reaper.py").read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(src) is None
    assert "boto3" not in src
    assert 'NAME_PREFIX = "hub-t3-"' in src
    assert "hub-t3-" in src


@pytest.mark.req("AWS-TEST-PLANE")
def test_weekly_drill_plants_fake_purpose_test_and_asserts_gone():
    """Weekly drill plants Fake purpose=test, reaps, asserts gone, writes AWS_REAPER.

    What would make this fail: planting purpose=prod, leaving the instance,
    or writing Kind.REAPER as if Multipass covered AWS.
    """
    from core.models import CheckRun
    from monitor.drills import run_aws_reaper_drill

    provider = RecordingCloud()
    with override_settings(**AWS_WALL):
        run = run_aws_reaper_drill(
            provider=provider, account_id=ACCOUNT, region_name=REGION,
        )
    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.kind == CheckRun.Kind.AWS_REAPER
    assert stored.status == CheckRun.Status.SUCCEEDED
    planted_id = stored.results["planted_id"]
    assert planted_id
    assert provider.get_instance(planted_id) is None
    assert any(
        c[0] == "create_instance"
        and (c[1].get("tags") or {}).get("purpose") == "test"
        for c in provider.calls
    )
    assert any(c[0] == "terminate_instance" for c in provider.calls)


def test_harness_reaper_test_plane_is_not_claimed_for_aws():
    """HARNESS-REAPER-TEST-PLANE is Multipass only; AWS uses AWS-TEST-PLANE.

    What would make this fail: marking cloud-reaper tests with the Multipass
    req, or claiming that id from monitor/cloud_reaper.py.
    """
    from conformance.check import collect_markers

    nodeids = collect_markers(REPO).get("HARNESS-REAPER-TEST-PLANE") or []
    claimed = [
        n for n in nodeids
        if "cloud_reaper" in n or "aws_terminate" in n or "test_aws_terminate" in n
    ]
    assert claimed == [], claimed
    cloud = (REPO / "monitor" / "cloud_reaper.py").read_text(encoding="utf-8")
    assert "HARNESS-REAPER-TEST-PLANE" not in cloud
