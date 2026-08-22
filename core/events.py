"""The ONE event-stream port product apps hold (§D7 · §F2 D-045 · §C4).

`realtime.publish` owns publish()/current_seq() — but core and monitor may not
import the realtime package: it reaches scanner via consumers.py's wire
escaping (R19-ARCH-1), and the ARCH-V6 gates walk the first-party import graph
at package granularity, keeping core and monitor scanner-free. So the
dependency points the only legal direction: realtime/apps.py::ready() calls
register_stream(publish, current_seq) once at startup, and every producer —
core.findings filing/transitioning, monitor.traffic landing TrafficStat rows —
calls through this module. There is exactly one slot: a second module-level
publisher (an earlier core.findings held its own) is how the two consumers
drift. Publishing or reading seq before the wiring is a boot-order bug and
fails loud rather than dropping events silently.
"""

_stream = None  # (publish_fn, current_seq_fn)


def register_stream(publish_fn, current_seq_fn):
    """Called once from realtime.apps.RealtimeConfig.ready()."""
    global _stream
    _stream = (publish_fn, current_seq_fn)


def _require():
    if _stream is None:
        raise RuntimeError(
            "event stream not wired — realtime.apps.RealtimeConfig.ready() "
            "must call core.events.register_stream()")
    return _stream


def publish(topic, event, history=False):
    return _require()[0](topic, event, history=history)


def current_seq(topic):
    return _require()[1](topic)
