"""§F8 v0: the seed loads and the replayer publishes scripted events through the
REAL publish() path (same seq counter, same channel layer the product uses)."""
import json
import pathlib
import warnings

import pytest

from realtime.authorize import authorize_topic
from realtime.publish import current_seq
from realtime.simulation import SEED, replay

pytestmark = pytest.mark.django_db


@pytest.mark.req("P0-SIM-REPLAYER")
def test_seed_loads_and_every_scripted_topic_is_subscribable():
    """A seed event the UI could never subscribe to is a fixture bug: every scripted
    topic must pass the same authorize_topic() choke point the socket enforces."""
    seed = json.loads(pathlib.Path(SEED).read_text())
    assert seed["scripted_events"], "seed has scripted events"
    assert len(seed["targets"]) == 4 and len(seed["sites"]) == 6  # §F8 v0 shape

    class AuthedUser:
        is_authenticated = True

    for entry in seed["scripted_events"]:
        assert authorize_topic(AuthedUser(), entry["topic"]), entry["topic"]


@pytest.mark.req("P0-SIM-REPLAYER")
def test_replay_publishes_through_real_path_with_monotonic_seqs():
    seed = json.loads(pathlib.Path(SEED).read_text())
    per_topic = {}
    for entry in seed["scripted_events"]:
        per_topic[entry["topic"]] = per_topic.get(entry["topic"], 0) + 1

    before = {t: current_seq(t) for t in per_topic}
    n = replay(speed=1e6)  # sleeps collapse; the publish path is what's under test
    assert n == len(seed["scripted_events"])
    for topic, count in per_topic.items():
        assert current_seq(topic) == before[topic] + count


# ── R9-Q2: the boundary neither suite crosses ──────────────────────────────────
#
# `frontend/src/sim.js` carries a scan report pasted out of a real run, and the node
# suite asserts the SCREENS render it correctly while this suite asserts what the
# SCANNER emits. Both stay green through a coordinated rename: change `core.secret-scan`
# to `core.secrets` in `scanner/modules/fallbacks.py` and in the python tests that name
# it, and nothing anywhere notices that sim.js — the demo, the thing people are shown —
# is now describing a scanner that does not exist. R8's fixture rot arrived by exactly
# that route, and its remedy (`scripts_dev/sim_fixture_repos.py`) made the fixture TREES
# re-derivable and stopped there.
#
# So: `scripts_dev/sim_fixture_payloads.py` completes the derivation — real scan, real
# `ReadinessSerializer` — and this compares its check ids and tiers against the ones
# embedded in sim.js's project-2 report.
#
# ADVISORY, per build-process §4's diff-coverage precedent ("advisory first, then
# blocking"): drift is reported as a warning in the run's warnings summary and the suite
# stays green. `BLOCKING` below is the one line that changes that, and the reason to
# wait is that this check spans two work streams — the frontend fixtures are edited in
# their own branch — so its first honest failures should be read before they can stop
# somebody's merge.
#
# DIRECTION, and it is deliberately one-way: an id in the live scan that sim.js does not
# carry is fine (a new check lands, the demo fixture catches up when someone refreshes
# it). An id in SIM.JS that the live scan does not emit at that tier is the finding —
# that is a rename, a removal, or a tier change, and it is the sentence "sim.js is
# fiction" in mechanical form.
#
# WHY PARSE sim.js AND NOT A GENERATED MANIFEST. The alternative the finding offered was
# emitting a fixtures-manifest JSON both sides check. It would parse more easily and it
# would check the wrong thing: a manifest is a third artifact that can agree with the
# scanner while sim.js disagrees with both. The value here is entirely in reading the
# bytes the browser actually loads. The parse is cheap because those payloads are pasted
# JSON — `json.loads` on the object literal, with an id/tier regex as the fallback for
# the day someone reformats or comments inside it.

import re  # noqa: E402 — grouped with this section rather than at the top

SIM_JS = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "sim.js"

# Flip to True to make sim.js drift fail the suite. See the section comment.
BLOCKING = True

_ID_TIER_RE = re.compile(r'"id":\s*"([^"]+)"\s*,\s*"tier":\s*"([^"]+)"')


def _sim_object_literal(text, name):
    """The `const <name> = { … };` body, by brace balance. None if it is not there."""
    start = text.find(f"const {name} = {{")
    if start < 0:
        return None
    start = text.index("{", start)
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def sim_check_tiers(name="MESSY_REPORT"):
    """`{check id: tier}` for every check sim.js's `name` payload carries.

    Two readings, cheapest first. The payloads are pasted JSON, so `json.loads` gives
    the exact structure and is immune to formatting; if that ever stops being true — a
    JS comment, a trailing comma, an interpolated value — the regex reads the same pairs
    out of the raw text and the check keeps working rather than turning into a parse
    error somebody silences.
    """
    text = SIM_JS.read_text(encoding="utf-8")
    body = _sim_object_literal(text, name)
    assert body, f"{name} is not in {SIM_JS}"
    try:
        payload = json.loads(body)
    except ValueError:
        return {cid: tier for cid, tier in _ID_TIER_RE.findall(body)}
    return {check["id"]: check["tier"]
            for key in ("blockers", "warnings", "advice", "pending_sandbox")
            for check in payload.get(key, [])}


def test_issue_r9_q2_sim_js_project_2_still_describes_the_live_scanner(tmp_path):
    """R9-Q2. Scan the committed fixture tree builder's output for real and compare the
    check ids and tiers against the ones sim.js's project-2 report shows.

    Tolerant of ADDITIONS in the live report and of nothing else, which is the axis a
    coordinated rename moves along. `tmp_path` rather than `/tmp`, because
    `sim_fixture_repos.write` starts by deleting its target and two runs racing on one
    hard-coded path is a flake rather than a finding.
    """
    import sys

    repo = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo / "scripts_dev"))
    import sim_fixture_payloads

    live = sim_fixture_payloads.check_tiers(
        sim_fixture_payloads.payloads(tmp_path, keys={"project-2"})["project-2"])
    shown = sim_check_tiers()

    assert shown, "sim.js's project-2 report names no checks at all"

    drift = []
    for check_id, tier in sorted(shown.items()):
        if check_id not in live:
            drift.append(f"sim.js shows {check_id!r} ({tier}); the scan of the messy "
                         f"fixture emits no such check — renamed or removed")
        elif live[check_id] != tier:
            drift.append(f"sim.js shows {check_id!r} at tier {tier!r}; the live scan "
                         f"reports it at {live[check_id]!r}")

    if not drift:
        return
    message = ("frontend/src/sim.js's project-2 report has drifted from the scanner:\n  "
               + "\n  ".join(drift)
               + "\n\nRegenerate it: python scripts_dev/sim_fixture_payloads.py "
                 "--project-2")
    if BLOCKING:
        raise AssertionError(message)
    warnings.warn(message, stacklevel=1)


def test_issue_r9_q2_the_drift_check_can_see_a_rename(tmp_path):
    """The gate's own gate. An advisory check that cannot fail is a green light wired to
    nothing, and this one's failure path is a warning nobody would notice missing — so
    the comparison is exercised against a deliberately renamed and re-tiered payload
    rather than trusted because it was read.
    """
    import sys

    repo = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo / "scripts_dev"))
    import sim_fixture_payloads

    live = sim_fixture_payloads.check_tiers(
        sim_fixture_payloads.payloads(tmp_path, keys={"project-2"})["project-2"])
    assert "core.secret-scan" in live and live["core.secret-scan"] == "blocker"

    shown = dict(live)
    shown["core.secrets"] = shown.pop("core.secret-scan")        # the rename
    shown["django.debug-hardcoded"] = "warning"                  # the tier change
    shown["core.declaration-file"] = "warning"                   # unchanged, must pass

    missing = [k for k in shown if k not in live]
    retiered = [k for k, t in shown.items() if k in live and live[k] != t]

    assert missing == ["core.secrets"]
    assert retiered == ["django.debug-hardcoded"]
    # …and an id the live scan has that sim.js does not is NOT drift.
    assert set(live) - set(shown) == {"core.secret-scan"}


def test_issue_r9_q2_the_sim_js_parse_survives_reformatting():
    """The parse is the fragile half, so both readings are exercised: the JSON path on
    the real file, and the regex fallback on a body `json.loads` refuses."""
    from_json = sim_check_tiers()
    assert "core.secret-scan" in from_json

    mangled = ('{ "blockers": [ {\n  // a comment json.loads will not take\n'
               '  "id":   "core.secret-scan" ,\n  "tier":\t"blocker"\n} ] }')
    assert dict(_ID_TIER_RE.findall(mangled)) == {"core.secret-scan": "blocker"}
