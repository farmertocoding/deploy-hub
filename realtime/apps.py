from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "realtime"

    def ready(self):
        # Wire the findings stream port (§F2, D-045): core files and
        # transitions Findings but may not import realtime (this package
        # reaches scanner via consumers.py, and ARCH-V6 keeps core/monitor
        # scanner-free), so the adapter is plugged in here, the direction
        # imports are already allowed to point.
        from core import findings

        from .publish import current_seq, publish

        findings.register_stream(publish, current_seq)
