"""EventsConsumer — the one multiplexed socket (§3.5/§D7).

Session-authenticated at connect (reject anonymous); client protocol
{action: subscribe|unsubscribe, topics: [...]}; topic string == group name.
"""
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from core.audit import audit
from scanner import presentation

from .authorize import authorize_topic


def _ws_json(payload):
    """A WebSocket frame, escaped against `CONTROL_CLASS` (R19-ARCH-1).

    The WS is a fourth device-reaching exit — a browser DevTools frame inspector, a `wscat`
    session, a proxy log all render what crosses it — and it was outside the presentation
    authority, safe only because stdlib `json.dumps` defaults `ensure_ascii=True` and so
    escapes the whole class as a side effect. `json_safe` makes that a RULE rather than a
    default: `topic` here is client-supplied and `event` is whatever `publish()` carried,
    both untrusted, and a future `ensure_ascii=False` for a CJK topic name cannot reopen
    the class. Idempotent over an already-ASCII-escaped string, so it costs nothing today.
    """
    return presentation.json_safe(json.dumps(payload))


class EventsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.topics = set()
        # Fail CLOSED by flag, not by timing (round-6 finding: relying on the
        # uninitialized set / transport teardown let a subscribe frame racing the
        # 4403 close be honored). receive() drops everything until this is True.
        self.authorized = False
        # Rejections ACCEPT first, then close with the app code: close() before
        # accept() becomes an HTTP 403 handshake rejection at daphne, the browser
        # sees 1006, and the client's terminal-code handling never fires
        # (round-4 finding, verified against the live wire).
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            # Same audit discipline as HTTP-side authz failures (round-1 finding).
            await database_sync_to_async(audit)(
                "ws_connect_rejected", source="ws", severity="security")
            await self.accept()
            await self.close(code=4401)
            return
        # §6.10 mandatory-2FA covers BOTH planes (round-2 finding: the HTTP
        # middleware gate alone left the realtime surface open to password-only
        # sessions of not-yet-enrolled users).
        if not await database_sync_to_async(_enrolled)(user):
            await database_sync_to_async(audit)(
                "ws_connect_rejected", source="ws", severity="security",
                actor=user, reason="enrollment_required")
            await self.accept()
            await self.close(code=4403)
            return
        if not await database_sync_to_async(_ws_verified)(self.scope):
            await database_sync_to_async(audit)(
                "ws_connect_rejected", source="ws", severity="security",
                actor=user, reason="verification_required")
            await self.accept()
            await self.close(code=4403)
            return
        self.authorized = True
        await self.accept()

    async def disconnect(self, code):
        for topic in getattr(self, "topics", set()):
            await self.channel_layer.group_discard(topic, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # True denial for rejected connections (round-6): frames arriving after an
        # accept-then-close rejection are dropped, never processed.
        if not getattr(self, "authorized", False):
            return
        try:
            msg = json.loads(text_data)
            action, topics = msg["action"], msg["topics"]
        except (ValueError, KeyError, TypeError):
            await self.send(_ws_json({"error": "bad message"}))
            return

        user = self.scope["user"]
        if action == "subscribe":
            for topic in topics:
                if await database_sync_to_async(authorize_topic)(user, topic):
                    self.topics.add(topic)
                    await self.channel_layer.group_add(topic, self.channel_name)
                    await self.send(_ws_json({"subscribed": topic}))
                else:
                    await database_sync_to_async(audit)(
                        "ws_topic_denied", source="ws", severity="security",
                        actor=user if user.is_authenticated else None, topic=topic)
                    await self.send(_ws_json({"denied": topic}))
        elif action == "unsubscribe":
            for topic in topics:
                self.topics.discard(topic)
                await self.channel_layer.group_discard(topic, self.channel_name)

    async def topic_event(self, message):
        if message.get("topic") == "findings":
            ws_id = (message.get("event") or {}).get("workspace_id")
            user = self.scope.get("user")
            if ws_id and not await database_sync_to_async(_user_in_workspace)(user, ws_id):
                return
        await self.send(_ws_json(
            {"topic": message["topic"], "seq": message["seq"], "event": message["event"]}
        ))


def _enrolled(user):
    from django_otp import devices_for_user

    return any(devices_for_user(user, confirmed=True))


def _ws_verified(scope):
    from django_otp import DEVICE_ID_SESSION_KEY

    session = scope.get("session") or {}
    if session.get(DEVICE_ID_SESSION_KEY):
        return True
    user = scope.get("user")
    checker = getattr(user, "is_verified", None)
    if callable(checker):
        return bool(checker())
    return False


def _user_in_workspace(user, workspace_id):
    from core.models import Workspace
    from core.rbac import workspace_membership

    workspace = Workspace.objects.filter(pk=workspace_id).first()
    return bool(workspace_membership(user, workspace))
