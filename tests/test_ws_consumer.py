"""EventsConsumer protocol tests through a real socket (round-1 finding: the
P0-AUTHZ-TOPIC claim 'anonymous sockets rejected' was only unit-tested on
authorize_topic, never proven through the consumer)."""
import json

import pytest
from asgiref.sync import sync_to_async
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

import realtime.routing
from realtime.publish import publish

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

APP = AuthMiddlewareStack(URLRouter(realtime.routing.websocket_urlpatterns))


async def _make_user(enrolled=True, username="ws-tester"):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user, _ = await sync_to_async(User.objects.get_or_create)(username=username)
    if enrolled:
        await sync_to_async(TOTPDevice.objects.get_or_create)(
            user=user, name="phone", defaults={"confirmed": True})
    return user


async def _connected_communicator():
    comm = WebsocketCommunicator(APP, "/ws/events/")
    comm.scope["user"] = await _make_user()
    connected, _ = await comm.connect()
    assert connected
    return comm


@pytest.mark.req("P0-2FA-TOTP")
async def test_unenrolled_session_rejected_on_ws_plane():
    """Round-2 finding: the HTTP-only gate left /ws/events/ open to password-only
    sessions of not-yet-enrolled users — both planes must enforce §6.10."""
    comm = WebsocketCommunicator(APP, "/ws/events/")
    comm.scope["user"] = await _make_user(enrolled=False, username="ws-unenrolled")
    connected, _ = await comm.connect()
    assert connected  # accept-then-close (round-4): code must reach the browser
    close = await comm.receive_output()
    assert close["type"] == "websocket.close" and close["code"] == 4403
    await comm.disconnect()


@pytest.mark.req("P0-AUTHZ-TOPIC")
async def test_anonymous_socket_rejected_with_4401():
    comm = WebsocketCommunicator(APP, "/ws/events/")  # no session → AnonymousUser
    connected, _ = await comm.connect()
    # Accept-then-close (round-4): the handshake succeeds so the app close code
    # actually reaches a real browser instead of a daphne-level HTTP 403 → 1006.
    assert connected
    close = await comm.receive_output()
    assert close["type"] == "websocket.close" and close["code"] == 4401
    await comm.disconnect()
    # The reject is audited like HTTP-side authz failures (round-1 finding).
    from core.models import AuditEvent

    exists = await sync_to_async(
        AuditEvent.objects.filter(action="ws_connect_rejected", severity="security").exists
    )()
    assert exists


@pytest.mark.req("P0-AUTHZ-TOPIC")
async def test_subscribe_denied_topic_refused_and_audited():
    comm = await _connected_communicator()
    await comm.send_to(json.dumps({"action": "subscribe", "topics": ["forbidden.topic!"]}))
    reply = json.loads(await comm.receive_from())
    assert reply == {"denied": "forbidden.topic!"}
    await comm.disconnect()
    from core.models import AuditEvent

    exists = await sync_to_async(
        AuditEvent.objects.filter(action="ws_topic_denied", severity="security").exists
    )()
    assert exists


@pytest.mark.req("P0-AUTHZ-TOPIC")
@pytest.mark.req("P0-REALTIME")
async def test_subscribe_receives_published_events_in_order():
    comm = await _connected_communicator()
    await comm.send_to(json.dumps({"action": "subscribe", "topics": ["demo.wstest.log"]}))
    assert json.loads(await comm.receive_from()) == {"subscribed": "demo.wstest.log"}

    await sync_to_async(publish)("demo.wstest.log", {"line": "one"})
    await sync_to_async(publish)("demo.wstest.log", {"line": "two"})

    m1 = json.loads(await comm.receive_from())
    m2 = json.loads(await comm.receive_from())
    assert m1["topic"] == "demo.wstest.log" and m1["event"] == {"line": "one"}
    assert m2["seq"] == m1["seq"] + 1  # channel-layer delivery, monotonic seq
    await comm.disconnect()


@pytest.mark.req("P0-AUTHZ-TOPIC")
async def test_unsubscribe_stops_delivery_and_bad_messages_answered():
    comm = await _connected_communicator()
    await comm.send_to(json.dumps({"action": "subscribe", "topics": ["demo.wstest2.log"]}))
    await comm.receive_from()  # subscribed ack
    await comm.send_to(json.dumps({"action": "unsubscribe", "topics": ["demo.wstest2.log"]}))
    # Sync point: the bad-message reply proves the unsubscribe above was processed
    # before we publish (ws input queue is ordered; the channel layer is not).
    await comm.send_to("not json")
    assert json.loads(await comm.receive_from()) == {"error": "bad message"}

    await sync_to_async(publish)("demo.wstest2.log", {"line": "after-unsub"})
    assert await comm.receive_nothing(timeout=0.3)
    await comm.disconnect()
