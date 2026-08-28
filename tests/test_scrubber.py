"""One scrubber for the nightly bundle and the pager (D-036).

Bearer headers, ntfy.sh/<topic> URLs, and vault refs join the high-entropy
class already covered by tests/test_nightly_failure_bundle.py.
"""
from __future__ import annotations


def _scrub():
    from monitor.scrub import scrub

    return scrub


def test_bearer_header_is_redacted():
    """What would make this fail: leaving `Bearer <token>` readable."""
    scrub = _scrub()
    raw = "Authorization: Bearer cf0XyZZtoken1234567890abcDEF"
    out = scrub(raw)
    assert "cf0XyZZtoken1234567890abcDEF" not in out
    assert "Bearer <redacted>" in out


def test_ntfy_topic_url_is_redacted():
    """What would make this fail: publishing https://ntfy.sh/<topic> verbatim
    (the topic name is a secret)."""
    scrub = _scrub()
    raw = "posted to https://ntfy.sh/hub-p1-unguessable-topic-name"
    out = scrub(raw)
    assert "hub-p1-unguessable-topic-name" not in out
    assert "ntfy.sh/<redacted>" in out


def test_multiple_token_classes_in_one_line():
    """What would make this fail: redacting only one shape when a line carries
    a Bearer header, an ntfy topic URL, and a vault ref together."""
    scrub = _scrub()
    raw = (
        "Authorization: Bearer S3cretT0kenAbCdEfGh1jK2lM3nO4pQ5rS6tU7vW8x "
        "https://ntfy.sh/hub-p2-another-secret-topic "
        "vault:ntfy-pub-hub"
    )
    out = scrub(raw)
    assert "S3cretT0kenAbCdEfGh1jK2lM3nO4pQ5rS6tU7vW8x" not in out
    assert "hub-p2-another-secret-topic" not in out
    assert "vault:ntfy-pub-hub" not in out
    assert "Bearer <redacted>" in out
    assert "ntfy.sh/<redacted>" in out
    assert "vault:<redacted>" in out
