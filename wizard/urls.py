from django.urls import path

from . import views

urlpatterns = [
    path("projects/", views.ProjectListView.as_view(), name="project-list"),
    path("projects/<int:project_id>/readiness/", views.ReadinessView.as_view(),
         name="readiness"),
    path("sites/<int:site_id>/wizard/", views.WizardView.as_view(), name="wizard"),
    path("sites/<int:site_id>/manifest/", views.ManifestView.as_view(),
         name="manifest"),
    path("sites/<int:site_id>/", views.SiteEdgeOwnerView.as_view(),
         name="site-detail"),
]
