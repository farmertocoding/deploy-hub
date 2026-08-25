from django.urls import path

from . import router_views, views

urlpatterns = [
    path("findings/", views.FindingListView.as_view(), name="findings-list"),
    path("findings/<int:pk>/", views.FindingDetailView.as_view(),
         name="findings-detail"),
    path("findings/<int:pk>/transition/", views.FindingTransitionView.as_view(),
         name="findings-transition"),
    path("map/", views.MapSnapshotView.as_view(), name="map-snapshot"),
    path("targets/", router_views.TargetListView.as_view(), name="target-list"),
    path("targets/<int:pk>/", router_views.TargetDetailView.as_view(),
         name="target-detail"),
    path("targets/<int:pk>/router-probe/", router_views.RouterProbeView.as_view(),
         name="target-router-probe"),
]
