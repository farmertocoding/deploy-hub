from django.urls import path

from deploys.hud import DeploymentCommandView, DeploymentDetailView, DeploymentsView
from deploys.hud_downloads import DeploymentDownloadGrantView, SignedDeploymentDownloadView

urlpatterns = [
    path("hud/deployments/", DeploymentsView.as_view(), name="hud-deployments"),
    path(
        "hud/deployments/<int:pk>/",
        DeploymentDetailView.as_view(),
        name="hud-deployment-detail",
    ),
    path(
        "hud/deployments/<int:pk>/commands/",
        DeploymentCommandView.as_view(),
        name="hud-deployment-command",
    ),
    path(
        "hud/deployments/<int:pk>/downloads/",
        DeploymentDownloadGrantView.as_view(),
        name="hud-deployment-download-grant",
    ),
    path(
        "hud/downloads/<str:token>/",
        SignedDeploymentDownloadView.as_view(),
        name="hud-signed-download",
    ),
]
