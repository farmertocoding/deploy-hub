from django.apps import AppConfig


class MonitorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "monitor"

    def ready(self):
        # One after_raise seam: antinoise installs over monitor.alerts.after_raise.
        from monitor import antinoise
        antinoise._install_hook()

        from django.db.models.signals import post_delete, post_save

        from core.models import NetworkZone, Site, SiteInstance, Target

        from .map_graph import notify_graph_changed

        # Collector/reconcile write cursors and payloads with update_fields;
        # those are not topology. A full save (create, or save() with no
        # update_fields) still publishes.
        _topology = {
            Target: {"host", "zone", "status", "lifecycle"},
            Site: {"name", "exposure", "primary_target", "domain"},
            SiteInstance: {"observed_state", "target", "site"},
            NetworkZone: {"name"},
        }

        def _changed(sender, **kwargs):
            update_fields = kwargs.get("update_fields")
            relevant = _topology.get(sender)
            if update_fields is not None and relevant is not None:
                if not relevant.intersection(update_fields):
                    return
            notify_graph_changed()

        for model in (NetworkZone, Target, Site, SiteInstance):
            post_save.connect(
                _changed, sender=model, dispatch_uid=f"map.graph.save.{model.__name__}",
            )
            post_delete.connect(
                _changed, sender=model, dispatch_uid=f"map.graph.delete.{model.__name__}",
            )
