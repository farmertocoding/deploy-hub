"""Phase 0 acceptance — each test is a literal transcription of one milestone clause
(review3 §Q4). check.py --phase 0 requires these green (or a WAIVERS.md line).
"""
import json

import pytest

pytestmark = [pytest.mark.acceptance(phase=0)]


@pytest.mark.req("P0-LOGIN")
@pytest.mark.django_db
def test_login_requires_valid_credentials(client):
    from django.contrib.auth.models import User

    User.objects.create_user("joseph", password="a-long-dev-password")
    bad = client.post("/api/auth/login/",
                      data=json.dumps({"username": "joseph", "password": "wrong"}),
                      content_type="application/json")
    assert bad.status_code == 400
    ok = client.post("/api/auth/login/",
                     data=json.dumps({"username": "joseph", "password": "a-long-dev-password"}),
                     content_type="application/json")
    assert ok.status_code == 200
    assert ok.json()["otp_enrolled"] is False  # first-run: UI forces enrollment


@pytest.mark.req("P0-VALIDATION")
@pytest.mark.django_db
def test_demo_form_errors_block_and_warnings_ask(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    u = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=u, name="phone", confirmed=True)  # §6.10 gate
    client.login(username="joseph", password="a-long-dev-password")

    # Error blocks with the §4.5 contract shape.
    r = client.post("/api/demo-jobs/", data=json.dumps({"name": "BAD NAME"}),
                    content_type="application/json")
    assert r.status_code == 400
    assert "name" in r.json()["errors"]
    assert {"code", "message", "hint"} <= set(r.json()["errors"]["name"][0])

    # Warning asks (409 + warnings), then confirm_warnings proceeds.
    slow = {"name": "demo", "delay": 3.0}
    r = client.post("/api/demo-jobs/", data=json.dumps(slow), content_type="application/json")
    assert r.status_code == 409
    assert r.json()["warnings"][0]["code"] == "slow_demo"
    r = client.post("/api/demo-jobs/", data=json.dumps({**slow, "confirm_warnings": True}),
                    content_type="application/json")
    assert r.status_code == 201


@pytest.mark.req("P0-REALTIME")
@pytest.mark.django_db
def test_demo_job_publishes_sequenced_events(client, settings):
    """Celery(eager) → publish() → sequence numbers monotonic from the same counter."""
    from realtime.publish import current_seq
    from realtime.tasks import demo_stream_logs

    demo_stream_logs("job-x", delay=0)
    assert current_seq("demo.job-x.log") == 9  # 8 lines + done event


@pytest.mark.req("P0-AUDIT")
@pytest.mark.django_db
def test_demo_job_start_is_audited(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import AuditEvent

    u = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=u, name="phone", confirmed=True)  # §6.10 gate
    client.login(username="joseph", password="a-long-dev-password")
    client.post("/api/demo-jobs/", data=json.dumps({"name": "demo"}),
                content_type="application/json")
    assert AuditEvent.objects.filter(action="demo_job_started").exists()


@pytest.mark.req("P0-WS-DEMO")
@pytest.mark.demo
def test_ws_reconnect_demo_recorded():
    """`verify: demo` clause — the socket-kill/reconnect walkthrough is a manual
    demo recorded in conformance/demos/phase-0.md; this marker ties it to the gate."""
    import pathlib

    demo = pathlib.Path(__file__).resolve().parent.parent.parent / "conformance/demos/phase-0.md"
    assert demo.exists()
