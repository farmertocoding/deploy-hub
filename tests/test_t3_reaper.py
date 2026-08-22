"""T1: reaper only deletes hub-t3-* (HARNESS-REAPER-TEST-PLANE)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

SOCK = "/var/run/docker.sock"


@pytest.mark.req("HARNESS-REAPER-TEST-PLANE")
def test_reaper_only_matches_hub_t3_prefix(tmp_path):
    """Listing + `.t3-lease` names: only `hub-t3-*` are deleted.

    What would make this fail: deleting `primary` / any name outside the prefix,
    or ignoring a prefix name written in a tmp lease file.
    """
    from tests.harness.multipass import (
        CLOUD_INIT,
        NAME_PREFIX,
        MultipassVM,
        delete_purge_argv,
        exec_argv,
        launch_argv,
        transfer_argv,
    )
    from tests.harness.reaper import reap_test_plane

    assert NAME_PREFIX == "hub-t3-"
    assert "sshd" in CLOUD_INIT or "ssh" in CLOUD_INIT
    assert "deploy" in CLOUD_INIT
    assert SOCK not in CLOUD_INIT
    assert "docker.sock" not in CLOUD_INIT

    vm = MultipassVM(name="hub-t3-probe", ipv4="10.0.0.8", user="deploy")
    launch = launch_argv("hub-t3-probe", cpus=1, mem="1G", disk="5G")
    assert isinstance(launch, list)
    assert all(isinstance(part, str) for part in launch)
    assert launch[0] == "multipass"
    assert "hub-t3-probe" in launch
    assert "22.04" in launch

    exe = exec_argv(vm, ["true"])
    assert exe == ["multipass", "exec", "hub-t3-probe", "--", "true"]

    xfer = transfer_argv("/tmp/a", "hub-t3-probe:/tmp/a")
    assert xfer == ["multipass", "transfer", "/tmp/a", "hub-t3-probe:/tmp/a"]

    purge = delete_purge_argv("hub-t3-probe")
    assert purge == ["multipass", "delete", "--purge", "hub-t3-probe"]

    lease_root = tmp_path / "tmp"
    lease_root.mkdir()
    (lease_root / ".t3-lease").write_text("hub-t3-leased\nprimary\n")
    (lease_root / "extra.t3-lease").write_text("hub-t3-from-file\n")

    deleted = []
    reap_test_plane(
        list_fn=lambda: ["primary", "hub-t3-orphan", "something-else"],
        delete_fn=deleted.append,
        lease_root=lease_root,
    )
    assert "primary" not in deleted
    assert "something-else" not in deleted
    assert set(deleted) == {"hub-t3-orphan", "hub-t3-leased", "hub-t3-from-file"}


@pytest.mark.req("HARNESS-REAPER-TEST-PLANE")
def test_reaper_idempotent_on_absent_name():
    """Absent `hub-t3-*` is success; a second reap is still success.

    What would make this fail: delete_purge / reap raising when the name is
    already gone.
    """
    from tests.harness.multipass import delete_purge
    from tests.harness.reaper import reap_test_plane

    def gone(argv):
        name = argv[-1]
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=f'instance "{name}" does not exist',
        )

    delete_purge("hub-t3-gone", run_fn=gone)
    delete_purge("hub-t3-gone", run_fn=gone)

    deleted = []
    reap_test_plane(list_fn=lambda: [], delete_fn=deleted.append)
    assert deleted == []
    reap_test_plane(list_fn=lambda: [], delete_fn=deleted.append)
    assert deleted == []


@pytest.mark.req("HARNESS-REAPER-TEST-PLANE")
def test_reaper_refuses_bare_name_without_prefix():
    """launch / delete_purge refuse names that do not start with `hub-t3-`.

    What would make this fail: deleting `ubuntu` or launching `primary` because
    a caller omitted the reaper prefix.
    """
    from tests.harness.multipass import T3NameError, delete_purge, launch
    from tests.harness.reaper import reap_test_plane

    with pytest.raises(T3NameError):
        delete_purge("orphan-vm")
    with pytest.raises(T3NameError):
        launch("orphan-vm", cpus=1, mem="1G", disk="5G")

    deleted = []
    reap_test_plane(list_fn=lambda: ["orphan-vm"], delete_fn=deleted.append)
    assert deleted == []
