from django.urls import path

from . import views

urlpatterns = [
    path("sites/<int:site_id>/env/", views.EnvView.as_view(), name="site-env"),
]
