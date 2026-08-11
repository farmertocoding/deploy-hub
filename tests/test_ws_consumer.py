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
@pytest.mark.req("SEC-610-MANDATORY-2FA")
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


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.req("P0-AUTHZ-TOPIC")
async def test_post_reject_frames_are_dropped():
    """Round-6 finding (empirical): after the accept-then-close(4403) rejection, a
    subscribe frame racing the close was honored (group_add executed) because the
    gate relied on transport timing. receive() must fail closed by flag."""
    comm = WebsocketCommunicator(APP, "/ws/events/")
    comm.scope["user"] = await _make_user(enrolled=False, username="ws-racer")
    connected, _ = await comm.connect()
    assert connected
    close = await comm.receive_output()
    assert close["type"] == "websocket.close" and close["code"] == 4403

    # The racing frame: must be silently dropped — no subscribed ack, no group_add.
    await comm.send_to(json.dumps({"action": "subscribe", "topics": ["demo.race.log"]}))
    assert await comm.receive_nothing(timeout=0.3)
    await comm.disconnect()


# ── SEC-A1-SESSION-AUTH: "WebSocket rides the same session" ────────────────────
#
# R4-11 WI-4: nothing proved this clause. Every test above hands the consumer a
# ready-made `scope["user"]`, which is exactly the step a session cookie is supposed
# to perform — so a Hub that authenticated sockets from a bearer token instead would
# keep them all green. This drives the PRODUCTION asgi application (hub.asgi), with
# no scope injection, using only the cookie a normal HTTP login planted.

@pytest.mark.req("SEC-A1-SESSION-AUTH")
async def test_issue_r4_11_ws_authenticates_from_the_http_login_session_cookie():
    from django.conf import settings
    from django.test import Client

    from hub.asgi import application

    await _make_user(username="ws-session-rider")

    def _login():
        from django.contrib.auth.models import User

        user = User.objects.get(username="ws-session-rider")
        user.set_password("a-long-dev-password")
        user.save()
        http = Client()
        assert http.login(username="ws-session-rider", password="a-long-dev-password")
        return http.cookies[settings.SESSION_COOKIE_NAME].value

    sessionid = await sync_to_async(_login)()
    headers = [
        (b"origin", b"http://testserver"),
        (b"cookie", f"{settings.SESSION_COOKIE_NAME}={sessionid}".encode()),
    ]

    comm = WebsocketCommunicator(application, "/ws/events/", headers=headers)
    connected, _ = await comm.connect()
    assert connected
    # No 4401: the socket resolved a real user from the session cookie alone.
    await comm.send_to(json.dumps({"action": "subscribe", "topics": ["demo.a1.log"]}))
    assert json.loads(await comm.receive_from()) == {"subscribed": "demo.a1.log"}
    await comm.disconnect()

    # …and the same socket with no session cookie is refused.
    anon = WebsocketCommunicator(application, "/ws/events/",
                                 headers=[(b"origin", b"http://testserver")])
    connected, _ = await anon.connect()
    assert connected
    close = await anon.receive_output()
    assert close["type"] == "websocket.close" and close["code"] == 4401
    await anon.disconnect()
