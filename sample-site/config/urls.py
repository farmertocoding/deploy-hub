"""GET /healthz — pinned JSON {live, ready, checks}. Optional DELAYED_READY_S."""
import os
import time

from django.http import JsonResponse
from django.urls import path

STARTED = time.monotonic()


def _delay_s():
    try:
        return float(os.environ.get("DELAYED_READY_S") or "0")
    except ValueError:
        return 0.0


def _ready():
    return (time.monotonic() - STARTED) >= _delay_s()


def healthz(_request):
    return JsonResponse({
        "live": True,
        "ready": _ready(),
        "checks": {
            "uptime_s": round(time.monotonic() - STARTED, 3),
            "delayed_ready_s": _delay_s(),
        },
    })


urlpatterns = [
    path("healthz", healthz),
    path("healthz.ready", healthz),
]
