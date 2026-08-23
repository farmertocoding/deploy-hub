"""CloudProvider test-plane reaper. No boto3 — list + terminate on the port.

After the D-066 wall, list_tagged_instances({purpose: test}) then
terminate_instance (absent == success). HUB_TEST_MODE=False is a no-op.
"""
from django.conf import settings

from core.test_mode import assert_test_aws


def reap_cloud_test_plane(provider, *, account_id, region_name):
    """Reap purpose=test instances on ``provider``. Writes CheckRun.AWS_REAPER."""
    from core.models import CheckRun
    from monitor.drills import RESULTS_SCHEMA_VERSION, record_run

    if not getattr(settings, "HUB_TEST_MODE", False):
        return record_run(
            CheckRun.Kind.AWS_REAPER,
            CheckRun.Status.SKIPPED,
            {
                "schema_version": RESULTS_SCHEMA_VERSION,
                "reason": "HUB_TEST_MODE is False",
                "n": 0,
            },
        )
    assert_test_aws(
        account_id, region_name, purpose="test", tags={"purpose": "test"},
    )
    tagged = provider.list_tagged_instances({"purpose": "test"})
    ids = []
    for inst in tagged:
        iid = inst["id"] if isinstance(inst, dict) else inst
        provider.terminate_instance(iid)
        ids.append(iid)
    return record_run(
        CheckRun.Kind.AWS_REAPER,
        CheckRun.Status.SUCCEEDED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "n": len(ids),
            "ids": ids,
        },
    )
