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


async def _connected_communicator():
    from django.contrib.auth.models import User

    user, _ = await sync_to_async(User.objects.get_or_create)(username="ws-tester")
    comm = WebsocketCommunicator(APP, "/ws/events/")
    comm.scope["user"] = user
    connected, _ = await comm.connect()
    assert connected
    return comm


@pytest.mark.req("P0-AUTHZ-TOPIC")
async def test_anonymous_socket_rejected_with_4401():
    comm = WebsocketCommunicator(APP, "/ws/events/")  # no session → AnonymousUser
    connected, close_code = await comm.connect()
    assert not connected
    assert close_code == 4401
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
