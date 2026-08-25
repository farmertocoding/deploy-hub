from django.apps import AppConfig


class DeploysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "deploys"

    def ready(self):
        # Core must not import deploys (kernel docstring / D4). The adapter
        # is plugged in here, the direction imports are already allowed to
        # point — same as realtime.apps.ready → core.events.register_stream.
        from core.overflow_deploys import (
            register_deploy,
            register_join,
            register_scale_in,
        )
        from core.partner_deploys import register_store
        from deploys.overflow import (
            overflow_copy_thunk,
            overflow_join_thunk,
            overflow_scale_in_thunk,
        )
        from deploys.partner_ledger import DjangoPartnerDeployStore

        register_store(DjangoPartnerDeployStore())
        register_deploy(overflow_copy_thunk)
        register_join(overflow_join_thunk)
        register_scale_in(overflow_scale_in_thunk)

