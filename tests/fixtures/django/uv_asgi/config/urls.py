from django.http import JsonResponse
from django.urls import path

urlpatterns = [
    path("healthz", lambda request: JsonResponse({"live": True, "ready": True, "checks": {}})),
]
