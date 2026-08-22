from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "realtime"

    def ready(self):
        # Wire the ONE event-stream port (§F2 D-045, §C4): core files and
        # transitions Findings, monitor lands TrafficStat rows — but neither
        # may import realtime (this package reaches scanner via consumers.py,
        # and ARCH-V6 keeps core/monitor scanner-free), so the adapter is
        # plugged in here, the direction imports are already allowed to
        # point. One registration serves every consumer: core.findings
        # delegates to core.events rather than holding a second slot.
        from core import events

        from .publish import current_seq, publish

        events.register_stream(publish, current_seq)
