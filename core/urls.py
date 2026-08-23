from django.urls import include, path

from . import otp, views, webauthn

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("totp/enroll/", otp.EnrollView.as_view(), name="totp-enroll"),
    path("totp/confirm/", otp.ConfirmView.as_view(), name="totp-confirm"),
    path("webauthn/touch/", webauthn.TouchView.as_view(), name="webauthn-touch"),
    path("webauthn/login/begin/", webauthn.LoginBeginView.as_view(),
         name="webauthn-login-begin"),
    path("webauthn/registration/complete/",
         webauthn.CompleteRegistrationView.as_view(),
         name="credential-registration-complete"),
    path("webauthn/", include("django_otp_webauthn.urls")),
]
