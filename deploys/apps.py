from django.apps import AppConfig


class DeploysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "deploys"

    def ready(self):
        # Core must not import deploys (kernel docstring / D4). The adapter
        # is plugged in here, the direction imports are already allowed to
        # point — same as realtime.apps.ready → core.events.register_stream.
        from core.partner_deploys import register_store
        from deploys.partner_ledger import DjangoPartnerDeployStore

        register_store(DjangoPartnerDeployStore())

