from django.urls import path

from . import zone_views

urlpatterns = [
    path("cloudflare/connect/", zone_views.CloudflareConnectView.as_view(),
         name="cloudflare-connect"),
]
