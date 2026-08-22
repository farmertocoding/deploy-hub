from django.apps import AppConfig


class MonitorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "monitor"

    def ready(self):
        # One after_raise seam: antinoise installs over monitor.alerts.after_raise.
        from monitor import antinoise
        antinoise._install_hook()
