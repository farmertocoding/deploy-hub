from django.apps import AppConfig


class ProvidersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "providers"

    def ready(self):
        from core.hud.ports import register_topic
        from providers.hud_workers import verify_integration

        register_topic("hud.integration.verify", verify_integration)
