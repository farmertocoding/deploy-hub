from django.urls import path

from . import views

urlpatterns = [
    path("projects/<int:project_id>/readiness/", views.ReadinessView.as_view(),
         name="readiness"),
    path("sites/<int:site_id>/wizard/", views.WizardView.as_view(), name="wizard"),
    path("sites/<int:site_id>/manifest/", views.ManifestView.as_view(),
         name="manifest"),
]
