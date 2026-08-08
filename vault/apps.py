from django.apps import AppConfig
from django.conf import settings


class VaultConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vault"

    def ready(self):
        """Fail loud at boot if the KEK is unusable (§6.9).

        A vault that starts fine and fails at first deploy is worse than one that
        refuses to start: the failure arrives mid-pipeline with a half-configured site.
        Skipped in DEBUG so a laptop `manage.py check` doesn't require a keyfile.
        """
        if settings.DEBUG or getattr(settings, "VAULT_SKIP_STARTUP_CHECK", False):
            return
        from .kek import get_backend

        get_backend().check()   # raises KEKError → boot aborts
