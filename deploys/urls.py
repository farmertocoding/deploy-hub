from django.urls import path

from . import views

urlpatterns = [
    path("sites/<int:site_id>/env/", views.EnvView.as_view(), name="site-env"),
    path(
        "sites/<int:site_id>/rollback/",
        views.SiteRollbackView.as_view(),
        name="site-rollback",
    ),
]
