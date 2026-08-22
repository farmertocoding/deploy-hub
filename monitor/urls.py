from django.urls import path

from . import views

urlpatterns = [
    path("findings/", views.FindingListView.as_view(), name="findings-list"),
    path("findings/<int:pk>/", views.FindingDetailView.as_view(),
         name="findings-detail"),
    path("findings/<int:pk>/transition/", views.FindingTransitionView.as_view(),
         name="findings-transition"),
    path("map/", views.MapSnapshotView.as_view(), name="map-snapshot"),
]
