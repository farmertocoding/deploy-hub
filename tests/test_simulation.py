"""§F8 v0: the seed loads and the replayer publishes scripted events through the
REAL publish() path (same seq counter, same channel layer the product uses)."""
import json
import pathlib

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
