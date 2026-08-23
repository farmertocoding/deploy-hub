"""T1 smoke: the seams and contracts exist and behave."""
import pytest

from core.transport import FakeTransport
from providers.fakes import FakeCloudProvider, FakeDnsProvider
from realtime.authorize import authorize_topic


class FakeUser:
    is_authenticated = True


class Anon:
    is_authenticated = False


@pytest.mark.req("P0-AUTHZ-TOPIC")
def test_authorize_topic_is_the_choke_point():
    user = FakeUser()
    assert authorize_topic(user, "demo.job-1.log")
    assert authorize_topic(user, "findings")
    assert not authorize_topic(user, "alerts")                 # D-045 alias retired
    assert not authorize_topic(user, "vault.secrets")          # unknown prefix
    assert not authorize_topic(user, "demo.$(evil).log")       # charset
    assert not authorize_topic(Anon(), "demo.job-1.log")       # anonymous


@pytest.mark.req("P0-SEAMS")
def test_fake_transport_rejects_shell_strings():
    t = FakeTransport()
    with pytest.raises(TypeError):
        t.run("rm -rf /")  # a string, not argv — the §4.5 injection rule
    result = t.run(["echo", "hello"])
    assert result.ok
    assert t.mutating_calls() == [("run", ["echo", "hello"])]


@pytest.mark.req("P0-SEAMS")
def test_fake_dns_upsert_is_idempotent():
    dns = FakeDnsProvider()
    rid1 = dns.upsert_record("example.com", "www", "A", ["1.2.3.4"], proxied=True)
    rid2 = dns.upsert_record("example.com", "www", "A", ["5.6.7.8"], proxied=True)
    assert rid1 == rid2
    assert len(dns.list_records("example.com")) == 1


@pytest.mark.req("P0-SEAMS")
def test_fake_cloud_terminate_is_idempotent():
    cloud = FakeCloudProvider()
    inst = cloud.create_instance({"size": "t3.small"})
    cloud.terminate_instance(inst["id"])
    cloud.terminate_instance(inst["id"])  # absent == success — reaper depends on this


@pytest.mark.django_db
def test_audit_helper_is_one_line():
    from core.audit import audit
    from core.models import AuditEvent

    audit("test_action", source="system", note="hello")
    ev = AuditEvent.objects.get()
    assert ev.action == "test_action"
    assert ev.detail == {"note": "hello"}
