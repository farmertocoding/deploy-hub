from django.urls import path

from . import views

urlpatterns = [
    path(
        "sites/<int:site_id>/backups/",
        views.BackupListView.as_view(),
        name="site-backups",
    ),
    path(
        "sites/<int:site_id>/backups/<int:unit_id>/test/",
        views.BackupTestNowView.as_view(),
        name="site-backup-test",
    ),
]
