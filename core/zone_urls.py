from django.urls import path

from . import checklist_views, zone_views

urlpatterns = [
    path("cloudflare/connect/", zone_views.CloudflareConnectView.as_view(),
         name="cloudflare-connect"),
    path("dns-accounts/<int:account_id>/origin-ca-plant/",
         zone_views.OriginCaPlantView.as_view(), name="origin-ca-plant"),
    path("first-run/", checklist_views.FirstRunView.as_view(), name="first-run"),
]
