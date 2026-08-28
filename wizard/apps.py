from django.apps import AppConfig


class WizardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wizard"

    def ready(self):
        from core.hud.ports import register_topic, register_wizard
        from wizard.create import create_project
        from wizard.hud_workers import scan_project
        from wizard.views import ProjectCreateSerializer, project_row_body

        register_wizard(
            create_project=create_project,
            ProjectCreateSerializer=ProjectCreateSerializer,
            project_row_body=project_row_body,
        )
        register_topic("hud.project.scan", scan_project)
