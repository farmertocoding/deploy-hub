"""ASGI entrypoint — HTTP via Django, WebSocket via Channels with session auth (§A1/§D7)."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")

from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

import realtime.routing  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(realtime.routing.websocket_urlpatterns))
        ),
    }
)
