"""T3: real ufw/fail2ban on a Multipass VM (HARNESS-T3-UFW-TRUTH)."""
from __future__ import annotations

import pytest

from tests.harness.multipass import multipass_available

pytest_plugins = ["tests.harness.t3_deploy"]

pytestmark = [
    pytest.mark.t3,
    pytest.mark.skipif(not multipass_available(), reason="multipass is not available"),
]

TAILNET_SLASH10 = "100.64.0.0/10"


def _exec(vm, argv, *, timeout=120):
    from tests.harness.multipass import exec as mp_exec

    return mp_exec(vm.mp(), argv, timeout=timeout)


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-UFW-TRUTH")
@pytest.mark.req("HARD-R1-TWO-POSTURES")
def test_ufw_active_on_multipass_vm(t3_ready):
    """ufw status is active on a Multipass VM, not hub-test-target.

    What would make this fail: skipping harden, or asserting against a container.
    """
    from tests.harness.t3_deploy import assert_not_hub_test_target

    assert_not_hub_test_target(t3_ready)
    result = _exec(t3_ready, ["sudo", "ufw", "status"])
    assert "Status: active" in (result.stdout or ""), result.stdout
    verbose = _exec(t3_ready, ["sudo", "ufw", "status", "verbose"])
    assert "cloudflare" in (verbose.stdout or "").lower(), verbose.stdout


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-UFW-TRUTH")
def test_fail2ban_active_on_multipass_vm(t3_ready):
    """fail2ban is-active on the VM after PROFILE=target harden.

    What would make this fail: jail.local written but the unit left inactive.
    """
    result = _exec(t3_ready, ["systemctl", "is-active", "fail2ban"])
    assert (result.stdout or "").strip() == "active", result.stdout


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-UFW-TRUTH")
@pytest.mark.req("HARD-R3-IGNOREIP")
def test_ignoreip_is_not_tailnet_slash10(t3_ready):
    """fail2ban ignoreip is the singular HUB_MESH_IP, never 100.64.0.0/10.

    What would make this fail: shipping the commented /10 line as live ignoreip.
    """
    from tests.harness.t3_deploy import HUB_MESH_IP

    result = _exec(
        t3_ready,
        ["sudo", "grep", "-E", r"^[[:space:]]*ignoreip", "/etc/fail2ban/jail.local"],
    )
    line = (result.stdout or "").strip()
    assert HUB_MESH_IP in line, line
    assert TAILNET_SLASH10 not in line, line


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-UFW-TRUTH")
def test_verify_hardening_target_profile_passes(t3_ready):
    """verify-hardening.sh PROFILE=target exits 0 on the hardened VM.

    Does not mark HARD-V2: mesh was skipped via documented HUB_T3_UFW_ONLY.
    What would make this fail: verify red after harden, harden claiming V2 on
    the skip-mesh path, or a manufactured tailscale0 standin greening the
    mesh posture on a VM with no tailnet (panel C2).
    """
    from tests.harness.multipass import exec_result
    from tests.harness.t3_deploy import HUB_MESH_IP

    result = _exec(
        t3_ready,
        [
            "sudo",
            "env",
            "PROFILE=target",
            f"HUB_MESH_IP={HUB_MESH_IP}",
            "/usr/local/sbin/verify-hardening.sh",
        ],
    )
    text = f"{result.stdout or ''} {result.stderr or ''}"
    assert "PASS" in text, text
    # The honest no-mesh output: harden said, in so many words, that HARD-V2
    # is not proven on this path.
    harden = t3_ready.harden_result
    assert harden is not None, "harden_target_profile never ran on this VM"
    harden_text = f"{harden.stdout or ''} {harden.stderr or ''}"
    assert "does not prove HARD-V2" in harden_text, harden_text
    # And no dummy standin exists to grep green: no tailscale0 interface, no
    # tailscale0 ufw rule on the no-mesh VM.
    link = exec_result(t3_ready.mp(), ["ip", "link", "show", "tailscale0"], timeout=30)
    assert link.returncode != 0, (
        f"tailscale0 exists on a no-mesh VM: {link.stdout!r}"
    )
    verbose = _exec(t3_ready, ["sudo", "ufw", "status", "verbose"])
    assert "tailscale0" not in (verbose.stdout or ""), verbose.stdout


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-UFW-TRUTH")
def test_inner_docker_is_overlay2_not_vfs(t3_ready):
    """Guest docker storage driver is overlay2, not the T2 vfs false-green.

    What would make this fail: running this inside hub-test-target (vfs).
    """
    result = _exec(
        t3_ready,
        ["sudo", "docker", "info", "--format", "{{.Driver}}"],
    )
    driver = (result.stdout or "").strip()
    assert driver == "overlay2", driver
    assert "vfs" not in driver


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-UFW-TRUTH")
def test_not_running_inside_hub_test_target(t3_ready):
    """systemd-detect-virt is kvm/qemu/multipass, never docker.

    What would make this fail: pointing these asserts at hub-test-target.
    """
    from tests.harness.t3_deploy import (
        assert_hub_docker_sock_absent,
        assert_not_hub_test_target,
    )

    assert_not_hub_test_target(t3_ready)
    assert_hub_docker_sock_absent(t3_ready)
