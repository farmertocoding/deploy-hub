"""D-022 / D-023: GHA QEMU is optional and vars-gated; skipped GHA is not the gate."""
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_nightly_workflow_qemu_job_is_vars_gated():
    """What would make this fail: a t3-qemu job that runs unconditionally, or no
    vars.HUB_ENABLE_GHA_QEMU guard (default unset must skip; skipped GHA is not
    the phase gate).
    """
    path = REPO / ".github" / "workflows" / "nightly.yml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    jobs = doc.get("jobs") or {}
    assert "t3-qemu" in jobs, "nightly.yml must declare an optional t3-qemu job"
    job = jobs["t3-qemu"]
    assert isinstance(job, dict)
    expr = str(job.get("if", ""))
    assert "vars.HUB_ENABLE_GHA_QEMU" in expr, (
        f"t3-qemu must be gated by vars.HUB_ENABLE_GHA_QEMU (got {expr!r})"
    )
