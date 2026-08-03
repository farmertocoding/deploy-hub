from django.urls import path

from . import otp, views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("totp/enroll/", otp.EnrollView.as_view(), name="totp-enroll"),
    path("totp/confirm/", otp.ConfirmView.as_view(), name="totp-confirm"),
]
