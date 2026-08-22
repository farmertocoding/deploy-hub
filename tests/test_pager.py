"""Pager seam and identities (D-036, ALERT-M3-PAGER-AUTH).

No test pages anyone: the default backend is FakePager. ntfy HTTP is
exercised only through a urlopen double.
"""
from __future__ import annotations

import pytest
from django.conf import settings
from django.core import mail

from core.models import AlertDelivery, Finding

pytestmark = [pytest.mark.django_db, pytest.mark.req("ALERT-M3-PAGER-AUTH")]

COPY = dict(
    title="Site is down",
    body="Three consecutive probes failed.",
    fix_action="Check docker on the target.",
)
ADVISORY = "advisory only — re-read from the Findings inbox before typing"
RAW_IP = "203.0.113.9"
RAW_SECRET = "S3cretT0kenAbCdEfGh1jK2lM3nO4pQ5rS6tU7vW8x"
BREAK_GLASS_CMD = "ssh root@203.0.113.9 'docker restart site-blog-141'"


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _file_p1(**overrides):
    from monitor.alerts import raise_alert

    fields = dict(COPY)
    fields.update(overrides)
    return raise_alert(
        "prod-site-hard-down",
        fields.pop("entity", "site:blog"),
        fingerprint=fields.pop("fingerprint", "site-down:blog-pager"),
        **fields,
    )


def test_publish_without_a_token_is_refused():
    """What would make this fail: ntfy accepting a bare topic with no token."""
    from providers.ntfy import NtfyPager, PagerAuthError

    pager = NtfyPager()
    with pytest.raises(PagerAuthError, match="token"):
        pager.publish(
            "p1",
            "title",
            "body",
            tags=["rotating_light"],
            click_url="/findings/1",
            topic="hub-p1-bare",
            token="",
        )


def test_hub_healthchecks_and_target_identities_are_distinct_refs():
    """What would make this fail: one shared vault ref for every publisher."""
    from providers.ntfy import publisher_ref

    hub = publisher_ref("hub")
    healthchecks = publisher_ref("healthchecks")
    target = publisher_ref("target:42")
    subscriber = settings.HUB_NTFY_SUBSCRIBER_REF
    assert hub != healthchecks != target
    assert hub != target
    assert len({hub, healthchecks, target, subscriber}) == 4
    assert hub == settings.HUB_NTFY_PUBLISHER_HUB_REF
    assert healthchecks == settings.HUB_NTFY_PUBLISHER_HEALTHCHECKS_REF


def test_subscriber_credential_is_never_used_to_publish(monkeypatch):
    """What would make this fail: publishing with the read/subscribe token."""
    from providers.ntfy import NtfyPager, PagerAuthError
    from vault import service as vault_service

    hub_token = "hub-publisher-token-AAAA-1111"
    sub_token = "subscriber-read-token-BBBB-2222"
    vault_service.put(
        kind="api_token",
        owner_type="ntfy",
        owner_id=settings.HUB_NTFY_PUBLISHER_HUB_REF,
        plaintext=hub_token.encode(),
    )
    vault_service.put(
        kind="api_token",
        owner_type="ntfy",
        owner_id=settings.HUB_NTFY_SUBSCRIBER_REF,
        plaintext=sub_token.encode(),
    )
    vault_service.put(
        kind="api_token",
        owner_type="ntfy",
        owner_id=settings.HUB_NTFY_TOPIC_P1_REF,
        plaintext=b"hub-p1-topic-name",
    )

    seen = []

    class _Resp:
        status = 200

        def read(self):
            return b""

    def _urlopen(request, timeout=None):
        seen.append(request.get_header("Authorization") or "")
        return _Resp()

    monkeypatch.setattr("providers.ntfy.urlopen", _urlopen)
    pager = NtfyPager()
    with pytest.raises(PagerAuthError, match="subscriber"):
        pager.publish(
            "p1",
            "title",
            "body",
            tags=["rotating_light"],
            click_url="/findings/1",
            token=sub_token,
            topic="hub-p1-topic-name",
        )
    assert seen == []

    pager.publish(
        "p1",
        "title",
        "body",
        tags=["rotating_light"],
        click_url="/findings/1",
        identity="hub",
    )
    assert seen, "hub publish never reached HTTP"
    assert sub_token not in seen[0]
    assert hub_token in seen[0]
    assert seen[0].startswith("Bearer ")


def test_push_body_has_no_raw_ip_no_secret_no_break_glass_command():
    """What would make this fail: a push that carries an IP, a secret, or a
    break-glass command (those live only in the email copy)."""
    from monitor.pager import get_pager

    row = _file_p1(
        entity=f"host:{RAW_IP}",
        fingerprint="site-down:ip-pager",
        title=f"DOWN at {RAW_IP}",
        body=(
            f"Host {RAW_IP} is unreachable. token={RAW_SECRET}. "
            f"Break-glass: {BREAK_GLASS_CMD}"
        ),
    )
    push = get_pager().published[-1]
    blob = f"{push['title']}\n{push['body']}"
    assert RAW_IP not in blob
    assert RAW_SECRET not in blob
    assert "docker restart" not in blob
    assert "ssh " not in blob.lower()
    assert BREAK_GLASS_CMD not in blob
    assert row.severity in blob
    assert push["click_url"]


def test_email_copy_carries_break_glass_marked_advisory_only():
    """What would make this fail: omitting the advisory prefix, or putting
    break-glass on the push channel."""
    from monitor.pager import get_pager

    _file_p1(fingerprint="site-down:bg-pager")
    assert mail.outbox, "P1 must send an email copy"
    body = mail.outbox[-1].body
    assert ADVISORY in body
    assert "docker" in body.lower() or "ssh" in body.lower()
    push = get_pager().published[-1]
    assert ADVISORY not in push["body"]
    assert "docker restart" not in push["body"]


def test_delivery_row_records_the_backend_and_the_outcome():
    """What would make this fail: an AlertDelivery with no backend, or ok
    that does not match whether the backend actually sent."""
    row = _file_p1(fingerprint="site-down:delivery-row")
    rows = list(AlertDelivery.objects.filter(finding=row))
    assert rows, "deliver() must write AlertDelivery rows"
    backends = {item.backend for item in rows}
    assert "fake" in backends
    ntfy = next(item for item in rows if item.channel == AlertDelivery.Channel.NTFY)
    assert ntfy.ok is True
    email = next(item for item in rows if item.channel == AlertDelivery.Channel.EMAIL)
    assert email.ok is True


def test_default_backend_in_tests_is_the_fake():
    """What would make this fail: tests resolving ntfy (or any live pager)."""
    from monitor.pager import get_pager
    from providers.fakes import FakePager

    assert settings.HUB_PAGER_BACKEND == "fake"
    assert isinstance(get_pager(), FakePager)


def test_p1_email_copy_is_sent_even_when_push_fails():
    """What would make this fail: a failed push swallowing the email copy."""
    from monitor.pager import get_pager

    get_pager().fail = True
    mail.outbox.clear()
    row = _file_p1(fingerprint="site-down:push-fails")
    assert mail.outbox, "email copy must still send when push fails"
    assert "[HUB P1]" in mail.outbox[-1].subject or "p1" in mail.outbox[-1].subject.lower()
    ntfy = AlertDelivery.objects.get(finding=row, channel=AlertDelivery.Channel.NTFY)
    assert ntfy.ok is False
    email = AlertDelivery.objects.get(finding=row, channel=AlertDelivery.Channel.EMAIL)
    assert email.ok is True


def test_failed_email_files_a_finding_and_does_not_block_the_push(monkeypatch):
    """What would make this fail: a mail error aborting the push, or silence
    (no Finding) when the paper trail cannot be sent."""
    from django.core import mail as django_mail

    from monitor.pager import get_pager

    def _boom(*args, **kwargs):
        raise OSError("smtp down")

    monkeypatch.setattr(django_mail, "send_mail", _boom)
    before = Finding.objects.count()
    row = _file_p1(fingerprint="site-down:email-fails")
    assert get_pager().published, "push must still go out"
    ntfy = AlertDelivery.objects.get(finding=row, channel=AlertDelivery.Channel.NTFY)
    assert ntfy.ok is True
    assert Finding.objects.count() > before
    filed = Finding.objects.exclude(pk=row.pk).latest("pk")
    assert filed.severity == Finding.Severity.P2
    assert "email" in (filed.title + filed.body + filed.fingerprint).lower()
