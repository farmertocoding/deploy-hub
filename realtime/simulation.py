"""Simulation-mode event replayer v0 (§F8).

Publishes scripted synthetic events through the REAL Channels path — the same
publish() the product uses — so UI failure states can be rendered and tested.
Run: python manage.py shell -c "from realtime.simulation import replay; replay()"
"""
import json
import pathlib
import time

from .publish import publish

SEED = pathlib.Path(__file__).resolve().parent.parent / "simulation/seed_v0.json"


def replay(speed=1.0):
    seed = json.loads(SEED.read_text())
    t_prev = 0
    for entry in seed["scripted_events"]:
        time.sleep(max(0, (entry["t"] - t_prev)) / speed)
        t_prev = entry["t"]
        publish(entry["topic"], entry["event"])
    return len(seed["scripted_events"])
