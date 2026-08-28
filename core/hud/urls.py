from django.urls import path

from core.hud.access import MembersView, RotatePlanView, SecretsView
from core.hud.collections import (
    AuditView,
    FindingsAdminView,
    IntegrationsView,
    OperationView,
    PartnersAdminView,
    ProjectsView,
    ProjectTestSourceView,
    SearchView,
    ShellView,
    TargetsAdminView,
)
from core.hud.commands import (
    FindingCommandView,
    IntegrationCommandView,
    PartnerCommandView,
    ProjectCommandView,
    SiteCommandView,
    TargetCollectionCommandView,
    TargetCommandView,
)
from core.hud.overview import OverviewView
from core.hud.sites import SiteDetailView, SitesFleetView

urlpatterns = [
    path("hud/overview/", OverviewView.as_view(), name="hud-overview"),
    path("hud/sites/", SitesFleetView.as_view(), name="hud-sites"),
    path("hud/sites/<int:pk>/", SiteDetailView.as_view(), name="hud-site-detail"),
    path("hud/secrets/", SecretsView.as_view(), name="hud-secrets"),
    path(
        "hud/secrets/<int:pk>/rotate-plan/",
        RotatePlanView.as_view(),
        name="hud-secret-rotate-plan",
    ),
    path("hud/members/", MembersView.as_view(), name="hud-members"),
    path("hud/projects/", ProjectsView.as_view(), name="hud-projects"),
    path("hud/targets/", TargetsAdminView.as_view(), name="hud-targets"),
    path("hud/findings/", FindingsAdminView.as_view(), name="hud-findings"),
    path("hud/partners/", PartnersAdminView.as_view(), name="hud-partners"),
    path("hud/integrations/", IntegrationsView.as_view(), name="hud-integrations"),
    path("hud/audit/", AuditView.as_view(), name="hud-audit"),
    path("hud/search/", SearchView.as_view(), name="hud-search"),
    path("hud/shell/", ShellView.as_view(), name="hud-shell"),
    path("hud/operations/<int:pk>/", OperationView.as_view(), name="hud-operation"),
    path(
        "hud/projects/test-source/",
        ProjectTestSourceView.as_view(),
        name="hud-project-test-source",
    ),
    path(
        "hud/projects/<int:pk>/commands/",
        ProjectCommandView.as_view(),
        name="hud-project-command",
    ),
    path(
        "hud/targets/commands/",
        TargetCollectionCommandView.as_view(),
        name="hud-target-collection-command",
    ),
    path(
        "hud/targets/<int:pk>/commands/",
        TargetCommandView.as_view(),
        name="hud-target-command",
    ),
    path(
        "hud/findings/<int:pk>/commands/",
        FindingCommandView.as_view(),
        name="hud-finding-command",
    ),
    path(
        "hud/partners/commands/",
        PartnerCommandView.as_view(),
        name="hud-partner-command",
    ),
    path(
        "hud/integrations/commands/",
        IntegrationCommandView.as_view(),
        name="hud-integration-command",
    ),
    path(
        "hud/sites/commands/",
        SiteCommandView.as_view(),
        name="hud-site-command",
    ),
]
