"""D-022 / D-023: GHA QEMU is optional and vars-gated; skipped GHA is not the gate."""
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_nightly_workflow_qemu_job_is_vars_gated():
    """What would make this fail: a t3-qemu job that runs unconditionally, or an
    ungated sibling (e.g. full-suite echo) that would post a green Check if
    Actions billing were ever re-enabled. Skipped GHA is not the phase gate.
    """
    path = REPO / ".github" / "workflows" / "nightly.yml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    jobs = doc.get("jobs") or {}
    assert "t3-qemu" in jobs, "nightly.yml must declare an optional t3-qemu job"
    for name, job in jobs.items():
        assert isinstance(job, dict), name
        expr = str(job.get("if", ""))
        assert "vars.HUB_ENABLE_GHA_QEMU" in expr, (
            f"job {name!r} is ungated and would post a Check if Actions is "
            f"enabled (got if={expr!r})"
        )
