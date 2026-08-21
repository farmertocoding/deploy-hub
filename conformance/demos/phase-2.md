# Phase 2 exit demo — recorded (P2-PIPELINE-DEMO / REL-P2-HUB-DOWN-SITES-UP)

**Date:** 2026-08-21 · **Branch:** `phase-2` · **Recorded by:** Task 21 session
on HEAD `d055888` plus the acceptance/demo files in this change.

D-020 is **not** taken. Tasks 13–20 shipped; this record transcribes the MUST
demo (CI half executable here) and names the real-world half honestly.

## What the milestone asked

Design note §4 / plan-addendum §I Phase 2: deploy `sample-node-site/` through
the real pipeline to `hub-test-target`, **twice**, with resume-from-crash and
rollback; volumes survive. Real-world half: TAKKO through the same pipeline.
REL-P2: Hub stopped, site still serves (24h is the live form).

## Artifacts

| Artifact | What it is | Result |
|---|---|---|
| `phase-2/t1-acceptance.txt` | `tests/acceptance/test_phase_2.py` — T1 FakeTransport transcription | 8 passed in 0.86s |
| `phase-2/t2-pipeline.txt` | Task 13 T2 live path, re-run this session | 2 passed in 37.78s |
| `phase-2/rel-p2-hub-down.txt` | REL-P2 chaos: Hub not in the serving path; duration honest | T2 now; **not** 24h |
| `phase-2/takko-outstanding.txt` | TAKKO real-pipeline half | **not run** — no invented log |

## CI half (executable)

**In-repo fixture** `sample-node-site/` is the executable CI half. T1
(`FakeTransport` / `PipelineTransport`) is `tests/acceptance/test_phase_2.py`
and the Task 13 named tests. T2 is
`tests/test_pipeline_sample_node_site.py::test_t2_execute_sample_node_site_twice`:
`execute` + `SshTransport` to `hub-test-target`, twice; named volume still
inspects; Hub `docker.sock` is not bound.

**Task 13 original T2** (`fc45b1d`, fix round `dafeead`), from
`.superpowers/sdd/phase-2-tasks/task-13-report.md`:

- initial: `1 passed, 3 deselected in 34.51s`
- after overlay/heartbeat/runbook fixes: `test_t2_execute_sample_node_site_twice` `1 passed` in 35.93s
- image is alpine + stdlib HTTP, COPY from `sample-node-site/` (not `npm ci` on vfs)

**This session (2026-08-21):**

```
CONFORMANCE_RUN_REPORT=off .venv/bin/pytest \
  tests/test_pipeline_sample_node_site.py::test_t2_execute_sample_node_site_twice \
  tests/test_hub_test_target.py::test_hub_docker_sock_not_bound -q
..  2 passed in 37.78s
```

T1 second-deploy `mutating_calls() == []`, resume from `HUB_TEST_CRASH_AFTER_STEP`,
rollback as a new Deployment, named volume survival: transcribed in
`tests/acceptance/test_phase_2.py` (8 passed). Those clauses also live in
`tests/test_pipeline_sample_node_site.py`, `tests/test_rollback.py`,
`tests/test_crash_kill_matrix.py`.

## Real-world half (TAKKO)

**Not run in this session.** There is no TAKKO deploy log here. The in-repo
fixture is the executable CI half; TAKKO through the real pipeline remains the
real-world half still outstanding. See `phase-2/takko-outstanding.txt`.

## REL-P2 — Hub down, sites up

Duration is honest:

- **Now:** T2 chaos. After `execute()` returned, site HTTP was served by
  Caddy + the site container **on hub-test-target**. The Hub was the pytest
  process that drove SSH; it was not on the serving path. Hub `docker.sock`
  was not mounted into the target (`test_hub_docker_sock_not_bound` passed
  this session). That is seconds-to-a-minute, the length of the T2 run.
- **24h:** not run. No live fleet site exists to leave up for a day. `_docker_run_argv`
  does not yet pass `--restart unless-stopped`, so a target reboot is also
  unproven. The 24h drill is the live form when a site exists.

Do not read this record as a 24h drill.

## Follow-up, still open

1. TAKKO real-pipeline deploy (real-world half of P2-PIPELINE-DEMO).
2. REL-P2 24h chaos against a live site, once one exists.
3. `--restart unless-stopped` (and Caddy persist-to-disk) as the 24h
   dependencies; T2 today proves "Hub not in the serving path", not reboot survival.
