from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from core.partner_views import (
    PartnerApiKillSwitchView,
    PartnerDestinationRankView,
    PartnerSiteTakedownView,
    PartnerSuspendView,
)
from core.views import (
    InstanceCreateView,
    InstanceTerminateView,
    OverflowDeployView,
    SshRotateView,
    TargetDeleteView,
)

urlpatterns = [
    # §4.5: the schema is generated from serializers; the TS client + zod schemas
    # are generated from this — hand-written duplicates are banned.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # /admin: Tailscale-IP-bound + 2FA in deployment (§B10); dev convenience here.
    path("admin/", admin.site.urls),
    path("api/", include("realtime.urls")),
    path("api/auth/", include("core.urls")),
    path("api/v1/instance/create/", InstanceCreateView.as_view(),
         name="instance-create"),
    path("api/v1/targets/<int:pk>/delete/", TargetDeleteView.as_view(),
         name="target-delete"),
    path("api/v1/targets/<int:pk>/terminate/", InstanceTerminateView.as_view(),
         name="instance-terminate"),
    path("api/v1/targets/<int:pk>/ssh-rotate/", SshRotateView.as_view(),
         name="ssh-rotate"),
    path("api/v1/partners/<int:pk>/suspend/", PartnerSuspendView.as_view(),
         name="partner-suspend"),
    path("api/v1/partner-api/kill-switch/", PartnerApiKillSwitchView.as_view(),
         name="partner-api-kill-switch"),
    path("api/v1/sites/<int:pk>/takedown/", PartnerSiteTakedownView.as_view(),
         name="site-takedown"),
    path("api/v1/sites/<int:pk>/overflow-deploy/", OverflowDeployView.as_view(),
         name="site-overflow-deploy"),
    path("api/v1/partners/<int:pk>/destination-rank/",
         PartnerDestinationRankView.as_view(),
         name="partner-destination-rank"),
    path("api/v1/", include("wizard.urls")),
    path("api/v1/", include("deploys.urls")),
    path("api/v1/", include("provision.urls")),
    path("api/v1/", include("monitor.urls")),
    path("api/v1/", include("core.zone_urls")),
]
