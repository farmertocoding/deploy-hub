from django.urls import path

from . import zone_views

urlpatterns = [
    path("cloudflare/connect/", zone_views.CloudflareConnectView.as_view(),
         name="cloudflare-connect"),
    path("dns-accounts/<int:account_id>/origin-ca-plant/",
         zone_views.OriginCaPlantView.as_view(), name="origin-ca-plant"),
]
