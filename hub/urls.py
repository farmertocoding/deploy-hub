from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from core.views import TargetDeleteView

urlpatterns = [
    # §4.5: the schema is generated from serializers; the TS client + zod schemas
    # are generated from this — hand-written duplicates are banned.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # /admin: Tailscale-IP-bound + 2FA in deployment (§B10); dev convenience here.
    path("admin/", admin.site.urls),
    path("api/", include("realtime.urls")),
    path("api/auth/", include("core.urls")),
    path("api/v1/targets/<int:pk>/delete/", TargetDeleteView.as_view(),
         name="target-delete"),
    path("api/v1/", include("wizard.urls")),
    path("api/v1/", include("deploys.urls")),
    path("api/v1/", include("provision.urls")),
    path("api/v1/", include("monitor.urls")),
    path("api/v1/", include("core.zone_urls")),
]
