"""The publish seam product apps are allowed to hold (§D7, ARCH-V6).

`realtime.publish.publish` is the only event API producers need — but the
import-rule gate walks the first-party graph at package granularity, and
`realtime` (consumers.py) legitimately imports `scanner` for outbound-frame
sanitization. A `monitor -> realtime` (or `core -> realtime`) import line
would therefore read as a monitor/core -> scanner edge, which ARCH-V6 forbids.

So the dependency is inverted: this module never mentions realtime; realtime's
AppConfig.ready() registers the real publisher here at startup, and producers
in monitor/ (traffic, later alerts) call `core.events.publish`. Before apps
are ready there is nothing to publish to, so the forwarder is a no-op then.
"""

_publisher = None


def set_publisher(fn):
    """Called once from realtime.apps.RealtimeConfig.ready()."""
    global _publisher
    _publisher = fn


def publish(topic, event, history=False):
    """Forward to the registered realtime publisher; no-op before apps.ready()."""
    if _publisher is None:
        return None
    return _publisher(topic, event, history=history)
