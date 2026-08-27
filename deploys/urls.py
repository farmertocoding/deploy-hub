from django.urls import path

from . import adopt_views, preview_views, views

urlpatterns = [
    path("sites/<int:site_id>/env/", views.EnvView.as_view(), name="site-env"),
    path(
        "sites/<int:site_id>/rollback/",
        views.SiteRollbackView.as_view(),
        name="site-rollback",
    ),
    path(
        "sites/<int:site_id>/preview/",
        preview_views.SitePreviewCreateView.as_view(),
        name="site-preview-create",
    ),
    path(
        "sites/<int:site_id>/adopt/",
        adopt_views.SiteAdoptView.as_view(),
        name="site-adopt",
    ),
]
