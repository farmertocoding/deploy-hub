from django.apps import AppConfig


class MonitorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "monitor"

    def ready(self):
        # One after_raise seam: antinoise installs over monitor.alerts.after_raise.
        from monitor import antinoise
        antinoise._install_hook()

        from django.db.models.signals import post_delete, post_save

        from core.hud.ports import register_topic
        from core.models import NetworkZone, Site, SiteInstance, Target, workspace_of
        from monitor.hud_workers import probe_target

        from .map_graph import advise_topology, notify_graph_changed

        register_topic("hud.target.probe", probe_target)

        # Collector/reconcile write cursors with update_fields; those are not
        # topology. collect_payload is the r3 T1 observation — re-evaluate
        # without publishing map.graph (cursor stampede). A full save still
        # publishes.
        _topology = {
            Target: {"host", "zone", "status", "lifecycle"},
            Site: {"name", "exposure", "primary_target", "domain"},
            SiteInstance: {"observed_state", "target", "site"},
            NetworkZone: {"name"},
        }
        _advise = {
            Target: {"collect_payload"},
        }

        def _changed(sender, **kwargs):
            update_fields = kwargs.get("update_fields")
            relevant = _topology.get(sender)
            advise = _advise.get(sender, set())
            if update_fields is not None:
                fields = set(update_fields)
                if relevant is not None and relevant.intersection(fields):
                    notify_graph_changed(workspace_of(kwargs.get("instance")))
                    return
                if advise.intersection(fields):
                    advise_topology()
                return
            notify_graph_changed(workspace_of(kwargs.get("instance")))

        for model in (NetworkZone, Target, Site, SiteInstance):
            post_save.connect(
                _changed, sender=model, dispatch_uid=f"map.graph.save.{model.__name__}",
            )
            post_delete.connect(
                _changed, sender=model, dispatch_uid=f"map.graph.delete.{model.__name__}",
            )
