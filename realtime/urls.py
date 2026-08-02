from django.urls import path

from . import views

urlpatterns = [
    path("demo-jobs/", views.DemoJobView.as_view(), name="demo-jobs"),
    path("topics/<str:topic>/snapshot/", views.TopicSnapshotView.as_view(), name="topic-snapshot"),
]
