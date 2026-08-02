from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # /admin: Tailscale-IP-bound + 2FA in deployment (§B10); dev convenience here.
    path("admin/", admin.site.urls),
    path("api/", include("realtime.urls")),
    path("api/auth/", include("core.urls")),
]
