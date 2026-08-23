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


def _load_seed():
    return json.loads(pathlib.Path(SEED).read_text())


def _event_state(event):
    """observed / status / observed_state / state — the fields a badge would read."""
    return (event.get("observed") or event.get("observed_state")
            or event.get("status") or event.get("state"))


@pytest.mark.req("UX-F8-SIMULATION-STATES")
def test_seed_includes_warming():
    """A scripted event carries warming (observed/status) so the badge is renderable.

    What would make this fail: dropping the warming event, or spelling it only
    in a comment / site field the replayer never publishes.
    """
    assert any(
        _event_state(entry.get("event") or {}) == "warming"
        for entry in _load_seed()["scripted_events"]
    ), "seed has no scripted event with observed/status warming"


@pytest.mark.req("UX-F8-SIMULATION-STATES")
def test_seed_includes_data_stale():
    """A scripted event carries the data-stale badge (data-stale / data_stale).

    What would make this fail: omitting the badge, or using a generic 'stale'
    that is not the feed-staleness token.
    """
    tokens = ("data-stale", "data_stale")
    assert any(
        any(tok in json.dumps(entry.get("event") or {}) for tok in tokens)
        for entry in _load_seed()["scripted_events"]
    ), "seed has no data-stale / data_stale badge event"


@pytest.mark.req("UX-F8-SIMULATION-STATES")
def test_seed_includes_single_instance():
    """The seed shows a site with a single instance (site field or event).

    What would make this fail: every site looking multi-instance / scale-ready,
    with no instances:1 or single_instance mark.
    """
    seed = _load_seed()

    def marks_single(obj):
        if not isinstance(obj, dict):
            return False
        if obj.get("instances") == 1 or obj.get("single_instance") is True:
            return True
        if obj.get("scale_ready") is False:
            return True
        for key in ("kind", "badge", "mark", "scale"):
            val = obj.get(key)
            if isinstance(val, str) and val.replace("_", "-") in {
                "single-instance", "single-instance-only",
            }:
                return True
        return False

    assert (
        any(marks_single(site) for site in seed["sites"])
        or any(marks_single(entry.get("event") or {}) for entry in seed["scripted_events"])
    ), "seed shows no single-instance site"


@pytest.mark.req("UX-F8-SIMULATION-STATES")
def test_seed_includes_recreate_site_down_impact():
    """Recreate takes the site down: an event, or deploy_strategy=recreate + a down window.

    What would make this fail: recreate with no down window, or a down event
    only on a blue-green site.
    """
    seed = _load_seed()
    recreate_sites = {
        site.get("domain") for site in seed["sites"]
        if site.get("deploy_strategy") == "recreate"
    }
    down_states = {"down", "stopped", "absent", "offline"}
    for entry in seed["scripted_events"]:
        event = entry.get("event") or {}
        is_down = _event_state(event) in down_states
        is_recreate = (
            event.get("deploy_strategy") == "recreate" or "recreate" in json.dumps(event)
        )
        if is_recreate and is_down:
            return
        if is_down and event.get("site") in recreate_sites:
            return
    pytest.fail("seed has no recreate-down impact")


@pytest.mark.req("UX-F8-SIMULATION-STATES")
def test_seed_includes_deploy_failure_at_a_named_step():
    """A scripted deploy fails at a named §D2 step (e.g. health_check).

    What would make this fail: a generic deploy-failed event with no step, or
    a step name that is not in the D2 pipeline.
    """
    d2_steps = {
        "build", "ship", "migrate", "start_green", "health_check",
        "dns", "route_tls", "smoke_test", "cutover",
    }
    failed = {"failed", "fail", "error"}
    for entry in _load_seed()["scripted_events"]:
        event = entry.get("event") or {}
        step = event.get("step") or event.get("step_name") or event.get("name")
        status = event.get("status") or event.get("outcome") or event.get("result")
        if step in d2_steps and status in failed:
            return
    pytest.fail("seed has no deploy failure at a named D2 step")


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

# R10-A7: the remediation line, and it is a command that RUNS. It used to end
# `--project-2`, which `sim_fixture_payloads.main` has never accepted — it took its argv
# and did nothing with it, so an operator following the instruction got a full
# regeneration and believed they had scoped one. The generator now refuses arguments
# outright (exit 2, the `mutation_gate.py` precedent from this round), and this string
# is what it accepts.
REGENERATE = "python scripts_dev/sim_fixture_payloads.py"


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

    R10-A5: the JSON reading is `sim_fixture_payloads.check_tiers`, which is the same
    function applied to the LIVE payload on the other side of the comparison. It had a
    fourth copy of the payload's key tuple here, and a comparison whose two sides read
    their input with two different key lists is a comparison that can agree while the
    payloads differ.
    """
    text = SIM_JS.read_text(encoding="utf-8")
    body = _sim_object_literal(text, name)
    assert body, f"{name} is not in {SIM_JS}"
    try:
        payload = json.loads(body)
    except ValueError:
        return {cid: tier for cid, tier in _ID_TIER_RE.findall(body)}
    return _harness().check_tiers(payload)


def _harness():
    """`scripts_dev/sim_fixture_payloads`, importable from a test run."""
    import sys

    repo = pathlib.Path(__file__).resolve().parent.parent
    if str(repo / "scripts_dev") not in sys.path:
        sys.path.insert(0, str(repo / "scripts_dev"))
    import sim_fixture_payloads

    return sim_fixture_payloads


# ── R10-Q3: the gate's own gate re-implemented the gate ────────────────────────
#
# `…_can_see_a_rename` existed because an advisory check that cannot fail is a green
# light wired to nothing. It then wrote its own `missing` / `retiered` comprehensions
# instead of driving the comparison it exists to exercise, so it proved a property of
# itself. The demonstration is one line each: putting `if False` in front of BOTH real
# conditions in the gate below left all five tests in this file green — the gate found
# no drift because it can no longer see any, and its guard agreed because it was never
# looking at the gate.
#
# So the comparison is a function, and both of them drive it.


def drift_lines(shown, live, what="the scan of the fixture"):
    """One line per way sim.js's `{id: tier}` disagrees with the live scan's.

    DIRECTION, and it is deliberately one-way: an id in the LIVE scan that sim.js does
    not carry is fine — a new check lands and the demo fixture catches up when someone
    refreshes it. An id in SIM.JS that the live scan does not emit at that tier is the
    finding: a rename, a removal, or a tier change, which is the sentence "sim.js is
    fiction" in mechanical form.
    """
    lines = []
    for check_id, tier in sorted(shown.items()):
        if check_id not in live:
            lines.append(f"sim.js shows {check_id!r} ({tier}); {what} emits no such "
                         f"check — renamed or removed")
        elif live[check_id] != tier:
            lines.append(f"sim.js shows {check_id!r} at tier {tier!r}; the live scan "
                         f"reports it at {live[check_id]!r}")
    return lines


def report_drift(name, shown, live, what="the scan of the fixture"):
    """Raise (or warn, if `BLOCKING` is ever turned off again) for any drift found.

    The VERDICT half, separated from the comparison so a test can exercise the raise
    without having to manufacture a whole drifted fixture tree. Both halves need
    exercising for the same reason: a check nobody has ever seen fail is a check nobody
    knows can.
    """
    lines = drift_lines(shown, live, what)
    if not lines:
        return
    message = (f"frontend/src/sim.js's {name} has drifted from the scanner:\n  "
               + "\n  ".join(lines)
               + "\n\nRegenerate it: " + REGENERATE)
    if BLOCKING:
        raise AssertionError(message)
    warnings.warn(message, stacklevel=1)


# ── R10-A2: the gate looked at one payload of four ─────────────────────────────
#
# GATE CHANGE, and this is what it changes: the drift check ran over `project-2`
# (MESSY_REPORT) alone, because the harness's DB-free half carried its own two-entry
# table hardcoding project-1 and project-2. EDGE_REPORT and RESCANNED_REPORT were
# outside it — so the five stale edge payloads R10-Q2 found went past a blocking gate
# that was green because it was not looking at them. A gate whose scope is a hand-typed
# list of two is R4-12's finding, and this is the instance of it that already cost a
# round.
#
# The scope is now the tree inventory itself (`sim_fixture_payloads.SIM_REPORT_TREES`),
# so a fixture tree added there is a payload this gate compares, without an edit here.
#
# A payload naming no checks compares vacuously — {} against {} is never drift, and
# under the one-way direction rule an EMPTY sim.js payload over a check-emitting tree is
# additions-only, which is not drift either. So this set is the only thing standing
# between "the fixture is empty" and a green gate.
#
# EXEMPT BY NAME, not include by name (R10-BE-2). It was written the other way round —
# a list of the payloads that must name checks — and a list like that defaults the next
# payload somebody adds to vacuous-allowed: it would sit in the inventory, be scanned,
# be compared, and pass on an empty literal forever. The exemption is the reviewable act
# and the default is the strict one.
#
# CLEAN_REPORT is the only member and it earns it: its tree is the digest-pinned clean
# service and the scan emits nothing but `ok`. UNSCANNED_REPORT does not appear because
# it is exempted a level up — it has no tree and no inventory entry at all.
VACUOUS_OK = {"CLEAN_REPORT"}


def test_issue_r10_a2_every_sim_js_report_payload_still_describes_the_live_scanner(
        tmp_path):
    """R9-Q2, widened by R10-A2 to every report-carrying payload in sim.js. Scan the
    committed fixture trees for real and compare each payload's check ids and tiers
    against the ones the live scanner emits.

    `tmp_path` rather than `/tmp`, because `sim_fixture_repos.write` starts by deleting
    its target and two runs racing on one hard-coded path is a flake rather than a
    finding.
    """
    harness = _harness()
    live_payloads = harness.payloads(tmp_path)

    assert VACUOUS_OK <= set(live_payloads), sorted(live_payloads)

    for name in sorted(live_payloads):
        live = harness.check_tiers(live_payloads[name])
        shown = sim_check_tiers(name)
        if name in VACUOUS_OK:
            # …and the exemption is checked against the tree, not just honoured. A tree
            # that starts emitting findings under an exempt payload is the one case the
            # one-way rule cannot see: sim.js stays empty, every live id is an addition,
            # and the gate reports nothing forever.
            assert not live, (
                f"{name} is exempt from naming checks and its tree now emits "
                f"{sorted(live)} — the exemption has outlived its reason")
        else:
            assert shown, f"sim.js's {name} names no checks at all"
        report_drift(name, shown, live, f"the scan of {name}'s fixture tree")


def test_issue_r9_q2_the_drift_check_can_see_a_rename(tmp_path):
    """The gate's own gate, DRIVING the gate (R10-Q3). A deliberately renamed and
    re-tiered payload, through the same `drift_lines` the check above calls — so a
    comparison that stops comparing takes this test down with it instead of leaving it
    agreeing with itself.
    """
    harness = _harness()

    live = harness.check_tiers(
        harness.payloads(tmp_path, keys={"MESSY_REPORT"})["MESSY_REPORT"])
    assert "core.secret-scan" in live and live["core.secret-scan"] == "blocker"

    shown = dict(live)
    shown["core.secrets"] = shown.pop("core.secret-scan")        # the rename
    shown["django.debug-hardcoded"] = "warning"                  # the tier change
    shown["django.secret-dev-fallback"] = shown["django.secret-dev-fallback"]

    lines = drift_lines(shown, live, "the scan of the messy fixture")

    assert len(lines) == 2, lines
    assert "'core.secrets'" in lines[0] and "renamed or removed" in lines[0]
    assert "'django.debug-hardcoded'" in lines[1] and "'blocker'" in lines[1]
    # …and an id the live scan has that sim.js does not is NOT drift: the rename left
    # `core.secret-scan` on the live side only, and it produced no line.
    assert set(live) - set(shown) == {"core.secret-scan"}
    assert drift_lines(live, live) == []


def test_issue_r10_q3_the_blocking_verdict_raises():
    """The half no green run has ever executed. `BLOCKING` was flipped to True in
    9f80060 on the strength of a run in which it found nothing — which is the only
    state this branch has ever been observed in.

    Exercised through `report_drift` rather than by drifting a fixture, so the assertion
    is about the verdict and the message, and cannot be satisfied by a scanner change.
    """
    assert BLOCKING is True, "the gate is advisory; 9f80060 flipped it"

    with pytest.raises(AssertionError) as caught:
        report_drift("EDGE_REPORT", {"core.gone": "warning"}, {})

    message = str(caught.value)
    assert "EDGE_REPORT" in message
    assert "renamed or removed" in message
    assert REGENERATE in message, "a refusal without the remedy is a puzzle"


def test_issue_r10_q3_the_advisory_verdict_warns_instead(monkeypatch):
    """…and the other arm, which is what this check shipped as for one round and what it
    returns to if anyone turns it off. A `BLOCKING = False` that silently raised, or a
    True that silently warned, is the same defect in either direction."""
    monkeypatch.setattr("tests.test_simulation.BLOCKING", False)

    with pytest.warns(UserWarning, match="renamed or removed"):
        report_drift("EDGE_REPORT", {"core.gone": "warning"}, {})

    # No drift, no warning, either way round.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        report_drift("EDGE_REPORT", {"core.x": "ok"}, {"core.x": "ok"})


def test_issue_r9_q2_the_sim_js_parse_survives_reformatting():
    """The parse is the fragile half, so both readings are exercised: the JSON path on
    the real file, and the regex fallback on a body `json.loads` refuses."""
    from_json = sim_check_tiers()
    assert "core.secret-scan" in from_json

    mangled = ('{ "blockers": [ {\n  // a comment json.loads will not take\n'
               '  "id":   "core.secret-scan" ,\n  "tier":\t"blocker"\n} ] }')
    assert dict(_ID_TIER_RE.findall(mangled)) == {"core.secret-scan": "blocker"}


# ── R10-A6/A7: the harness's key names, and a remediation line that runs ───────

def test_issue_r10_a6_every_harness_key_is_a_sim_js_constant():
    """R10-A6. The keys of the generator's output ARE the constant names in sim.js, so
    regenerating is a splice rather than a translation step — and four of them were
    `*_PROJECT_ROW` against sim.js's `*_PROJECT`.

    A name that does not line up is not a cosmetic difference here: it is a payload
    quietly not spliced, in the file whose whole point is that nothing in it is typed.
    Read out of the generator's source rather than by running it, because running it
    needs a test database and this assertion is about names.
    """
    source = (pathlib.Path(__file__).resolve().parent.parent / "scripts_dev"
              / "sim_fixture_payloads.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'out\["([A-Z0-9_]+)"\]', source))
    declared = set(re.findall(r"^const ([A-Z0-9_]+) = \{",
                              SIM_JS.read_text(encoding="utf-8"), re.M))

    assert emitted, "the generator emits no keys at all"
    assert emitted <= declared, sorted(emitted - declared)


def test_issue_r10_a7_the_generator_refuses_arguments():
    """R10-A7. `main` took argv and ignored it, and the drift gate's own remediation
    line handed it `--project-2` — an option that has never existed. Someone following
    the instruction got a full regeneration and believed they had scoped one.

    Exit 2 rather than 1, the `mutation_gate.py` precedent from this round: the script
    declining to run is a different thing from a verdict about the fixtures.
    """
    harness = _harness()

    assert harness.main(["--project-2"]) == 2
    assert harness.main(["anything"]) == 2


def test_issue_r10_a7_the_remediation_line_is_a_command_that_runs():
    """…and the gate's message says what the generator accepts. A remediation line
    naming a flag its target refuses is worse than none: it is followed."""
    assert REGENERATE == "python scripts_dev/sim_fixture_payloads.py"
    assert "--" not in REGENERATE


def test_issue_r10_a2_the_gate_covers_every_report_payload_sim_js_carries(tmp_path):
    """The gate's scope, asserted rather than trusted. R10-Q2 got through because the
    scope was a two-entry table somebody had to remember to extend; naming the rule
    here means the next payload added to sim.js is either covered or is a failing test.

    UNSCANNED_REPORT is the one exemption and it is a real one: `orders-api` has never
    been scanned, there is no tree to scan, and its payload's four lists are empty by
    construction.
    """
    harness = _harness()
    declared = set(re.findall(r"^const ([A-Z0-9_]+_REPORT) = \{",
                              SIM_JS.read_text(encoding="utf-8"), re.M))

    assert declared - set(harness.SIM_REPORT_TREES) == {"UNSCANNED_REPORT"}
    assert set(harness.SIM_REPORT_TREES) <= declared, (
        "the inventory names a payload sim.js does not declare")
    assert set(harness.payloads(tmp_path)) == set(harness.SIM_REPORT_TREES)


def _secret_scan_titles(obj):
    """Every `core.secret-scan` title nested in a sim.js / readiness payload."""
    found = []
    if isinstance(obj, dict):
        if obj.get("id") == "core.secret-scan" and "title" in obj:
            found.append(obj["title"])
        for value in obj.values():
            found.extend(_secret_scan_titles(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_secret_scan_titles(value))
    return found


def test_sim_js_secret_scan_titles_match_the_scanner(tmp_path):
    """§F8 copies of `core.secret-scan` must use the scanner's current blocker title.

    The wording itself is closed (`cbe040d`); this pins that sim.js did not keep the
    pre-change string after the scanner moved.
    """
    harness = _harness()
    live = harness.payloads(tmp_path)
    shipped = []
    for name in ("MESSY_REPORT", "RESCANNED_REPORT"):
        shipped.extend(_secret_scan_titles(live[name]))
    assert shipped, "the messy/rescanned trees must still emit core.secret-scan"
    expected = shipped[0]
    assert all(title == expected for title in shipped), shipped

    text = SIM_JS.read_text(encoding="utf-8")
    names = re.findall(r"^const ([A-Z0-9_]+) = \{", text, re.M)
    shown = []
    for name in names:
        body = _sim_object_literal(text, name)
        if not body:
            continue
        try:
            payload = json.loads(body)
        except ValueError:
            continue
        for title in _secret_scan_titles(payload):
            shown.append((name, title))
    assert shown, "sim.js carries no core.secret-scan title to pin"
    drifted = [(name, title) for name, title in shown if title != expected]
    assert not drifted, (
        f"core.secret-scan title drifted from the scanner's {expected!r}: {drifted}\n"
        f"Regenerate it: {REGENERATE}"
    )


def test_issue_r10_a2_the_scan_stamp_is_spelled_once(tmp_path):
    """The harness carried ISO strings restating `CLEAN_AT`/`MESSY_AT`, three lines
    below their own definitions. It now passes the datetimes and the serializer renders
    them — and what it renders has to be what sim.js shows, or the two spellings had
    already drifted and nobody would have known.
    """
    harness = _harness()
    live = harness.payloads(tmp_path)

    for name, payload in sorted(live.items()):
        shown = json.loads(_sim_object_literal(SIM_JS.read_text(encoding="utf-8"), name))
        assert payload["scanned_at"] == shown["scanned_at"], name


# ── R11-A3: the tree inventory, and the two programs that wrote it ────────────
#
# `sim_fixture_repos.__main__` had its own directory→dict mapping and wrote five trees
# from it; `sim_fixture_payloads.build_trees` wrote the same five from its own table. Two
# programs, one inventory, agreeing by inspection. And `build()` — the DB half that
# produces every non-readiness payload in sim.js — wrote NOTHING: it derived
# `/tmp/cleanrepo` and scanned whatever happened to be there.

def test_issue_r11_a3_the_repo_builder_and_the_harness_write_the_same_trees(tmp_path):
    """One inventory, and `write_all` is what both entry points call.

    `sim_fixture_repos.TREES` is the spelling; `build_trees` translates its directory
    names into sim.js constant names and adds nothing else.
    """
    harness = _harness()
    from sim_fixture_repos import SUPPORT_TREES, TREES, write_all

    by_directory = write_all(tmp_path / "direct")
    assert set(by_directory) == set(TREES)

    by_constant = harness.build_trees(tmp_path / "harness")
    assert set(by_constant) == set(harness.SIM_REPORT_TREES)
    for key, tree in harness.SIM_REPORT_TREES.items():
        assert by_constant[key].name == tree.directory

    # The same bytes on both paths — a second writer that dropped the symlinks, or the
    # support tree, would be a fixture that differs from the one the operator builds.
    for directory in TREES:
        direct = (tmp_path / "direct" / directory)
        if directory not in {t.directory for t in harness.SIM_REPORT_TREES.values()}:
            assert directory in SUPPORT_TREES
            continue
        mirror = tmp_path / "harness" / directory
        assert sorted(p.relative_to(direct).as_posix() for p in direct.rglob("*")) == \
            sorted(p.relative_to(mirror).as_posix() for p in mirror.rglob("*"))


def test_issue_r11_a3_every_written_tree_is_a_payload_tree_or_a_support_tree():
    """The hole R10-BE-1 disclosed and left open, closed.

    A new dict added to `sim_fixture_repos` and wired into `TREES` used to fire nothing
    at all — nothing scanned that module for trees — so a fixture tree could exist,
    be written on every run, and be compared against no payload by any gate. It is now
    one of two named things: a tree some sim.js payload comes from, or a support tree
    that carries no payload and says so.
    """
    harness = _harness()
    from sim_fixture_repos import SUPPORT_TREES, TREES

    payload_trees = {t.directory for t in harness.SIM_REPORT_TREES.values()}
    assert payload_trees <= set(TREES), sorted(payload_trees - set(TREES))
    assert set(SUPPORT_TREES) <= set(TREES), sorted(set(SUPPORT_TREES) - set(TREES))
    assert set(TREES) == payload_trees | set(SUPPORT_TREES), (
        "a tree is written on every run and named by neither inventory: "
        f"{sorted(set(TREES) - payload_trees - set(SUPPORT_TREES))}")


def test_issue_r11_a3_the_support_tree_is_written_before_the_tree_that_links_into_it(
        tmp_path):
    """`edgerepo`'s committed symlink resolves INTO `edge-neighbour`. Written the other
    way round, the link points at nothing at the moment the scan reads it — and a broken
    link is a DIFFERENT refusal, with different wording, from an escaping one. The
    ordering used to be a property of two loops in `build_trees`; it is now a property of
    `write_all`, which is what both entry points call.
    """
    from sim_fixture_repos import SUPPORT_TREES, write_all

    roots = write_all(tmp_path)
    link = roots["edgerepo"] / "packages/server/src/metrics.ts"

    assert "edge-neighbour" in SUPPORT_TREES
    assert link.is_symlink()
    assert link.resolve().is_file(), (
        "the link is dangling — the neighbour tree was written after the tree that "
        "points at it")


def test_issue_r11_a3_the_db_harness_scans_the_trees_it_writes(monkeypatch, tmp_path):
    """`build()` derived `/tmp/cleanrepo` and scanned whatever was on disk there.

    Asserted through the seam rather than by running the whole capture, which needs a
    test database: `build` now calls `build_trees(base)` and reads the roots it returns,
    so a stale `/tmp` cannot decide what sim.js's payloads say. If the call goes away,
    the sentinel below is never asked for and this fails.
    """
    harness = _harness()
    asked = []

    def fake_build_trees(base):
        asked.append(pathlib.Path(base))
        raise _StopBuild

    monkeypatch.setattr(harness, "build_trees", fake_build_trees)
    with pytest.raises(_StopBuild):
        harness.build(tmp_path)

    assert asked == [tmp_path], "build() did not write the trees it is about to scan"


class _StopBuild(Exception):
    """Ends `build()` at the seam under test — everything after it needs a database."""
