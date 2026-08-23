from django.urls import path

from . import aws_views, checklist_views, partner_views, zone_views

urlpatterns = [
    path("partners/", partner_views.PartnerListCreateView.as_view(),
         name="partner-list-create"),
    path("partners/<int:pk>/", partner_views.PartnerDetailView.as_view(),
         name="partner-detail"),
    path("aws/connect/", aws_views.AwsConnectView.as_view(), name="aws-connect"),
    path("cloudflare/connect/", zone_views.CloudflareConnectView.as_view(),
         name="cloudflare-connect"),
    path("dns-accounts/<int:account_id>/origin-ca-plant/",
         zone_views.OriginCaPlantView.as_view(), name="origin-ca-plant"),
    path("first-run/", checklist_views.FirstRunView.as_view(), name="first-run"),
]
