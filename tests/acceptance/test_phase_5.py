"""Phase 5 acceptance — each test transcribes one design-note §4 clause.

`check.py --phase 5 --exclude-tier t2 --exclude-tier t3` is the phase-5 gate.
T1 fakes/moto only: FakeCloudProvider, FakeIam, FakeSsm, FakeImageRegistry,
FakeTransport, FakeHelper, moto on providers/{ec2,route53,ssm,aws_creds}.py.
Do not require live AWS. Do not invent HUB_TEST_AWS_TOKEN or HUB_TEST_CF_TOKEN.
Do not add Playwright. Do not claim SSH-CA enablement. DNS-01 stays the
phase-4 first slip. Do not claim a 24 h Hub-down.

Every T1 body asserts the same properties an existing named proof asserts
(transcription, not fiction); each docstring names its source test.
The demo record must describe those proofs, not a fictional live run.
P5-AWS-DEMO is verify: demo of the file — no MUST @pytest.mark.req here.
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from django.test import override_settings

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "conformance" / "demos" / "phase-5.md"
WAIVER_24H = "REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven"
DNS01_ID = "TLS-B2-HUB-DNS01-UNPROXIED"
FULL_TEXT_SEC_B2 = "SEC-B2-NO-DNS-TOKENS-ON-TARGETS"
AKI = "t1-aws-access-key-id-not-a-credential"
SAK = "t1-aws-secret-access-key-not-a-credential"
NAV_IDS = ["home", "sites", "targets", "deploys", "findings", "settings"]
NAMED = (
    "test_empty_ref_paints_degraded_not_connected",
    "test_connect_observes_before_vault_put",
    "test_connect_201_never_echoes_keys",
    "test_iam_refuse_files_aws_scope",
    "test_t1_create_shows_cost_fake_0_05",
    "test_enroll_public_key_only_ssh_key_ref_before_transport",
    "test_pin_before_transport",
    "test_empty_pin_refuses_transport",
    "test_target_delete_terminates_then_deletes",
    "test_terminate_failure_does_not_delete_row",
    "test_instance_terminate_is_t1",
    "test_route53_fail_closed_proxied_raises_l5_notify_only",
    "test_ensure_ship_none_docker_loads",
    "test_fake_registry_tls_auth_split_creds",
    "test_ssm_get_only_no_target_keys",
    "test_cloud_reaper_vs_multipass",
    "test_empty_allowlist_ref_and_default_chain_refuse",
    "test_nav_stays_six",
)

pytestmark = [pytest.mark.acceptance(phase=5)]


def _waivers():
    return (REPO / "WAIVERS.md").read_text(encoding="utf-8")


def _demo():
    assert DEMO.is_file() and DEMO.stat().st_size > 0, (
        "conformance/demos/phase-5.md must exist — P5-AWS-DEMO is verify: demo"
    )
    text = DEMO.read_text(encoding="utf-8")
    assert text.strip(), "a whitespace-only demo is not a record"
    return text


def _registry():
    data = yaml.safe_load((REPO / "conformance" / "requirements.yaml").read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["requirements"]}


def _waiver_lines(fingerprint):
    prefix = f"WAIVED: {fingerprint} "
    return [line for line in _waivers().splitlines() if line.startswith(prefix)]


def _assert_honest_t1_demo():
    """A non-empty stub must not verify P5-AWS-DEMO (Task 0)."""
    record = _demo()
    lower = record.lower()
    for name in NAMED:
        assert name in record, f"demo must name the acceptance nodeid {name}"
    assert "FakeCloudProvider" in record
    assert "FakeIam" in record
    assert "FakeSsm" in record
    assert "FakeImageRegistry" in record
    assert "FakeTransport" in record
    assert "FakeHelper" in record
    assert "moto" in lower
    assert "t1" in lower
    assert "live aws" not in lower or "no live" in lower or "not a live" in lower
    assert "ssh-ca" in lower or "ssh ca" in lower
    assert "evaluation" in lower
    assert "enablement" in lower
    assert (
        "not enable" in lower
        or "does not enable" in lower
        or ("not" in lower and "enablement" in lower)
    )
    assert "docs/ssh-ca-evaluation.md" in record
    assert DNS01_ID in record
    assert "first slip" in lower
    assert WAIVER_24H in record
    assert "24 h hub-down" not in lower and "24h hub-down" not in lower
    assert "playwright" not in lower or "no playwright" in lower or "slip" in lower
    assert "HUB_TEST_" + "AWS_TOKEN" not in record
    assert "HUB_TEST_" + "CF_TOKEN" not in record
    assert "HUB_TEST_" + "DNS_ZONE" not in record
    assert "stub" not in lower
    assert "todo" not in lower
    assert "conformance-5" in lower
    assert "--exclude-tier t2" in record and "--exclude-tier t3" in record
    assert "P5-AWS-DEMO" in record
    assert "§4" in record or "section 4" in lower
    return record


def _star_doc():
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    }


# ── named clauses ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_empty_ref_paints_degraded_not_connected(client):
    """Empty AWS_CREDENTIALS_REF paints degraded, never Connected.

    Transcribes tests/test_aws_creds.py::
    test_settings_unconfigured_is_degraded_not_connected and
    frontend/tests/settings-aws.test.ts::
    aws_tab_exists_paste_is_write_only_degraded_empty_and_error.
    """
    from test_aws_creds import CONNECT, _enrolled_client

    _enrolled_client(client)
    with override_settings(AWS_CREDENTIALS_REF=""):
        response = client.get(CONNECT)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body.get("connected") is False
    blob = json.dumps(body)
    assert "HUB_AWS_CREDENTIALS_REF" in blob
    assert "Connected" not in blob

    src = (REPO / "frontend" / "src" / "screens" / "Settings.jsx").read_text(encoding="utf-8")
    start = src.find("export function AwsStatusBanner")
    end = src.find("export function CloudflarePanel")
    aws_fn = src[start:end]
    assert re.search(r"not connected", aws_fn, re.I)
    assert "Connected" not in aws_fn


@pytest.mark.django_db
def test_connect_observes_before_vault_put(client, monkeypatch):
    """Write-only paste is observed (GetCallerIdentity + IAM allowlist,
    including groups) before any vault write.

    Transcribes tests/test_aws_creds.py::test_connect_observes_before_vault_write.
    """
    from test_aws_creds import test_connect_observes_before_vault_write

    test_connect_observes_before_vault_write(client, monkeypatch)


@pytest.mark.django_db
def test_connect_201_never_echoes_keys(client, monkeypatch):
    """201 names account last-4 and region; pasted keys never come back.

    Transcribes tests/test_aws_creds.py::test_connect_201_never_echoes_keys.
    """
    from test_aws_creds import test_connect_201_never_echoes_keys

    test_connect_201_never_echoes_keys(client, monkeypatch)


@pytest.mark.django_db
def test_iam_refuse_files_aws_scope():
    """`*` / AdministratorAccess / group-attached Admin / NotAction refuse
    and file kind aws-scope fingerprint aws-scope:{account_id} with refs,
    not secrets.

    Transcribes tests/test_aws_creds.py::test_star_action_refuses_and_files_aws_scope,
    ::test_administrator_access_refuses,
    ::test_group_attached_administrator_access_refuses,
    ::test_not_action_refuses, ::test_finding_body_has_refs_never_secret,
    and ::test_finding_fingerprint_is_aws_scope_account_id.
    """
    from test_aws_creds import ACCOUNT as A
    from test_aws_creds import REF as R
    from test_aws_creds import _findings

    from core.models import Finding
    from monitor.alert_rules import classify
    from providers.aws_creds import AwsScopeError, FakeIam, refuse_iam_scope

    with pytest.raises(AwsScopeError, match=r"\*"):
        refuse_iam_scope(documents=[_star_doc()], account_id=A, ref=R)
    row = _findings().get()
    assert row.fingerprint == f"aws-scope:{A}"
    assert row.fingerprint != "aws-scope"
    assert row.severity == Finding.Severity.P2
    assert classify("aws-scope") == "p2"
    blob = json.dumps(
        {
            "title": row.title,
            "body": row.body,
            "fix_action": row.fix_action,
            "entity": row.entity,
            "fingerprint": row.fingerprint,
        }
    )
    assert R in row.body
    assert A in row.body or A in row.fingerprint
    assert AKI not in blob and SAK not in blob
    assert "secret_access_key" not in blob

    Finding.objects.all().delete()
    iam = FakeIam(
        attached=[
            {
                "name": "AdministratorAccess",
                "arn": "arn:aws:iam::aws:policy/AdministratorAccess",
                "document": _star_doc(),
            }
        ]
    )
    with pytest.raises(AwsScopeError, match="AdministratorAccess"):
        refuse_iam_scope(iam=iam, account_id=A, ref=R)

    Finding.objects.all().delete()
    group_iam = FakeIam(
        groups=["admins"],
        group_attached={
            "admins": [
                {
                    "name": "AdministratorAccess",
                    "arn": "arn:aws:iam::aws:policy/AdministratorAccess",
                    "document": _star_doc(),
                }
            ]
        },
    )
    with pytest.raises(AwsScopeError, match="AdministratorAccess"):
        refuse_iam_scope(iam=group_iam, account_id=A, ref=R)
    assert _findings().filter(fingerprint=f"aws-scope:{A}").exists()

    Finding.objects.all().delete()
    not_action = {"Statement": [{"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"}]}
    with pytest.raises(AwsScopeError, match="NotAction"):
        refuse_iam_scope(documents=[not_action], account_id=A, ref=R)
    assert _findings().get().fingerprint == f"aws-scope:{A}"


@pytest.mark.django_db
def test_t1_create_shows_cost_fake_0_05(client, monkeypatch):
    """T1 instance.create shows $0.05/h (Fake) as T1Overlay.cost and
    requires WebAuthn touch + type-the-name.

    Transcribes tests/test_ec2_provider.py::test_estimate_hourly_cost_fake_is_0_05,
    tests/test_aws_enroll.py::test_cost_visible_on_overlay_before_confirm,
    ::test_instance_create_is_t1,
    ::test_instance_create_refuses_without_recent_touch, and
    ::test_instance_create_requires_type_the_name.
    """
    from test_aws_enroll import (
        CREATE_URL,
        HOST,
        RecordingCloud,
        _create_body,
        _t1_user,
        _touch,
        test_instance_create_is_t1,
    )

    from core.actions import ACTION_TIERS
    from core.models import Target
    from core.transport import FakeTransport
    from providers.fakes import FakeCloudProvider
    from provision.aws_enroll import enroll_aws_target as real_enroll

    assert FakeCloudProvider().estimate_hourly_cost({"instance_type": "t3.small"}) == 0.05

    row = next(r for r in ACTION_TIERS if r["id"] == "instance.create")
    assert row["tier"] == "T1"
    assert row["label"] == "Create target"
    test_instance_create_is_t1()

    tiers = (REPO / "frontend" / "src" / "Tiers.jsx").read_text(encoding="utf-8")
    assert "five cents per hour" in tiers
    start = tiers.find("export function T1Overlay")
    end = tiers.find("export function ActionButton")
    overlay = tiers[start:end]
    assert overlay.find("costText") < overlay.find("Confirm —")

    _t1_user(client)
    body, _zone_row = _create_body()
    refused = client.post(
        CREATE_URL,
        data=json.dumps(body),
        content_type="application/json",
    )
    assert refused.status_code == 403, refused.content
    assert "touch" in refused.json()["detail"].lower()
    assert not Target.objects.filter(host=HOST).exists()

    _touch(client, monkeypatch)
    provider = RecordingCloud(cost=0.05)
    transport = FakeTransport(
        responses={
            "ss": {"stdout": ""},
            "docker": {"stdout": ""},
            "crontab": {"stdout": ""},
            "env": {"exit_code": 1, "stdout": ""},
        }
    )

    def patched(**kwargs):
        kwargs.setdefault("provider", provider)
        kwargs.setdefault("make_transport", lambda target: transport)
        return real_enroll(**kwargs)

    monkeypatch.setattr("provision.aws_enroll.enroll_aws_target", patched)
    wrong = client.post(
        CREATE_URL,
        data=json.dumps(_create_body(confirm_name="wrong-host", zone=_zone_row)[0]),
        content_type="application/json",
    )
    assert wrong.status_code == 400, wrong.content
    ok = client.post(
        CREATE_URL,
        data=json.dumps(_create_body(confirm_name=HOST, zone=_zone_row)[0]),
        content_type="application/json",
    )
    assert ok.status_code in (200, 201), ok.content
    assert Target.objects.filter(host=HOST, kind="aws_ec2").exists()


@pytest.mark.django_db
def test_enroll_public_key_only_ssh_key_ref_before_transport():
    """Hub-mints SSH (public-only inject, ssh_key_ref before Transport);
    create_instance uses IMDSv2 hop-limit 1 and no public 22 (moto).

    Transcribes tests/test_aws_enroll.py::test_userdata_or_keypair_is_public_key_only,
    ::test_enroll_sets_ssh_key_ref_before_transport, and
    tests/test_ec2_provider.py::test_runinstances_requires_imdsv2_and_hop_limit_1
    plus ::test_default_sg_has_no_public_22.
    """
    from test_aws_enroll import PRIVATE_MARKERS, _enroll
    from test_ec2_provider import (
        test_default_sg_has_no_public_22,
        test_runinstances_requires_imdsv2_and_hop_limit_1,
    )

    from vault.models import Secret

    result, provider, transport, events = _enroll()
    assert events, "Transport must run after the key is vaulted"
    assert events[0]["ssh_key_ref"]
    secret = Secret.objects.get(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_id=events[0]["ssh_key_ref"],
    )
    assert secret.pk
    creates = [c for c in provider.calls if c[0] == "create_instance"]
    assert creates
    spec = creates[0][1]
    blob = json.dumps(spec)
    for marker in PRIVATE_MARKERS:
        assert marker not in blob
    pub = spec.get("ssh_public_key") or spec.get("public_key") or ""
    assert pub.startswith("ssh-ed25519")
    assert spec.get("KeyName") in (None, "")
    assert "AWS_ACCESS_KEY_ID" not in blob
    src = (REPO / "provision" / "aws_enroll.py").read_text(encoding="utf-8")
    assert "CreateKeyPair" not in src
    del result, transport

    test_runinstances_requires_imdsv2_and_hop_limit_1()
    test_default_sg_has_no_public_22()


@pytest.mark.django_db
def test_pin_before_transport():
    """host_key_fingerprint is pinned before provision_host; kind=aws_ec2
    and provider_ref are stored.

    Transcribes tests/test_aws_enroll.py::test_pin_happens_before_any_transport
    and ::test_kind_aws_ec2_and_provider_ref_and_host_written.
    """
    from test_aws_enroll import HOST, _enroll

    from core.models import Target

    result, provider, transport, events = _enroll()
    assert events, "provision_host must run over a Transport after the pin"
    assert events[0]["host_key_fingerprint"]
    assert events[0]["host_key_fingerprint"].startswith("SHA256:")
    creates = [c for c in provider.calls if c[0] == "create_instance"]
    assert creates, "create_instance must run so there is a pin to write"
    src = (REPO / "provision" / "aws_enroll.py").read_text(encoding="utf-8")
    assert "AutoAdd" not in src
    assert "WarningPolicy" not in src

    target = Target.objects.get(host=HOST)
    assert target.kind == Target.Kind.AWS_EC2
    assert target.provider_ref
    assert target.provider_ref.startswith("i-")
    assert target.host == HOST
    assert target.host != target.provider_ref
    assert events[0]["kind"] == Target.Kind.AWS_EC2
    assert events[0]["provider_ref"] == target.provider_ref
    del result, transport


@pytest.mark.django_db
def test_empty_pin_refuses_transport():
    """Empty pin still refuses Transport (never TOFU).

    Transcribes tests/test_aws_enroll.py::test_empty_pin_still_refuses_transport.
    """
    from test_aws_enroll import test_empty_pin_still_refuses_transport

    test_empty_pin_still_refuses_transport()


@pytest.mark.django_db
def test_target_delete_terminates_then_deletes(client, monkeypatch):
    """target.delete on aws_ec2 terminates (absent == success) then deletes.

    Transcribes tests/test_aws_terminate.py::
    test_target_delete_on_aws_ec2_terminates_then_deletes and
    ::test_terminate_absent_is_success.
    """
    from test_aws_terminate import (
        RecordingCloud,
        _aws_target,
        _delete_url,
        _inject_provider,
        _t1_user,
        _touch,
        test_terminate_absent_is_success,
    )

    from core.models import Target

    _t1_user(client)
    _touch(client, monkeypatch)
    provider = RecordingCloud()
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"])
    pk = target.pk
    _inject_provider(monkeypatch, provider)

    response = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 204, response.content
    assert any(c[0] == "terminate_instance" and c[1] == inst["id"] for c in provider.calls)
    assert inst["id"] not in provider.instances
    assert not Target.objects.filter(pk=pk).exists()

    test_terminate_absent_is_success()


@pytest.mark.django_db
def test_terminate_failure_does_not_delete_row(client, monkeypatch):
    """Terminate failure keeps the Django row so the operator can retry.

    Transcribes tests/test_aws_terminate.py::
    test_terminate_failure_does_not_delete_row and
    ::test_terminate_finding_fingerprint_is_aws_terminate_target_pk.
    """
    from test_aws_terminate import (
        RecordingCloud,
        _aws_target,
        _delete_url,
        _inject_provider,
        _t1_user,
        _touch,
    )

    from core.models import Finding, Target
    from provision.aws_enroll import TerminateError, terminate_aws_target

    _t1_user(client)
    _touch(client, monkeypatch)
    provider = RecordingCloud(fail_terminate=True)
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"])
    pk = target.pk
    _inject_provider(monkeypatch, provider)

    response = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 400, response.content
    assert Target.objects.filter(pk=pk).exists()
    assert inst["id"] in provider.instances
    target.refresh_from_db()
    assert target.provider_ref == inst["id"]

    failing = RecordingCloud(fail_terminate=True)
    boom = failing.create_instance({"tags": {"purpose": "test"}})
    stuck = _aws_target(provider_ref=boom["id"])
    with pytest.raises(TerminateError):
        terminate_aws_target(stuck, provider=failing)
    row = Finding.objects.get(fingerprint=f"aws-terminate:{stuck.pk}")
    assert row.severity == Finding.Severity.P1
    assert "aws-terminate-failed" not in row.fingerprint


@pytest.mark.django_db
def test_instance_terminate_is_t1():
    """instance.terminate is T1 and does not leave READY.

    Transcribes tests/test_aws_terminate.py::test_instance_terminate_is_t1
    and ::test_instance_terminate_does_not_leave_ready_target.
    """
    from test_aws_terminate import test_instance_terminate_does_not_leave_ready_target
    from test_aws_terminate import test_instance_terminate_is_t1 as _is_t1

    _is_t1()
    test_instance_terminate_does_not_leave_ready_target()


@pytest.mark.django_db
def test_route53_fail_closed_proxied_raises_l5_notify_only():
    """Route 53 dns_provider_for is fail-closed; proxied=True raises;
    L5 against that zone is notify-only.

    Transcribes tests/test_route53_provider.py::
    test_dns_provider_for_route53_fail_closed, ::test_upsert_proxied_true_raises,
    and tests/test_attack_playbook.py::test_l5_against_route53_zone_is_notify_only.
    """
    from test_attack_playbook import test_l5_against_route53_zone_is_notify_only
    from test_route53_provider import (
        test_dns_provider_for_route53_fail_closed,
        test_upsert_proxied_true_raises,
    )

    from monitor.pager import reset_pager
    from providers.registry import reset_scope_cache

    test_dns_provider_for_route53_fail_closed()
    test_upsert_proxied_true_raises()
    reset_pager()
    reset_scope_cache()
    test_l5_against_route53_zone_is_notify_only()


def test_ensure_ship_none_docker_loads():
    """ensure_ship with registry=None still docker-loads.

    Transcribes tests/test_image_registry.py::test_ensure_ship_none_still_docker_loads.
    """
    from test_image_registry import test_ensure_ship_none_still_docker_loads

    test_ensure_ship_none_still_docker_loads()


def test_fake_registry_tls_auth_split_creds():
    """Fake registry requires TLS+auth and split push/pull creds.

    Transcribes tests/test_image_registry.py::test_fake_registry_requires_tls_and_auth,
    ::test_push_cred_is_not_pull_cred, and ::test_pull_cred_is_per_target.
    """
    from test_image_registry import (
        test_fake_registry_requires_tls_and_auth,
        test_pull_cred_is_per_target,
        test_push_cred_is_not_pull_cred,
    )

    test_fake_registry_requires_tls_and_auth()
    test_push_cred_is_not_pull_cred()
    test_pull_cred_is_per_target()


@pytest.mark.django_db
def test_ssm_get_only_no_target_keys():
    """SSM pull writes Get-only parameters under /deploy-hub/{target.pk}/
    and never AWS_ACCESS_KEY_ID on the target.

    Transcribes tests/test_ssm.py::test_ssm_pull_uses_prefix_deploy_hub_target_pk,
    ::test_instance_profile_policy_is_get_only, and
    ::test_no_aws_access_key_id_on_target.
    """
    from test_ssm import (
        test_instance_profile_policy_is_get_only,
        test_no_aws_access_key_id_on_target,
        test_ssm_pull_uses_prefix_deploy_hub_target_pk,
    )

    test_ssm_pull_uses_prefix_deploy_hub_target_pk()
    test_instance_profile_policy_is_get_only()
    test_no_aws_access_key_id_on_target()


@pytest.mark.django_db
def test_cloud_reaper_vs_multipass():
    """Cloud reaper lists purpose=test and terminates through the port
    (CheckRun.Kind.AWS_REAPER); Multipass reaper stays prefix-only.

    Transcribes tests/test_cloud_reaper.py::
    test_cloud_reaper_respects_allowlist_and_purpose_test,
    ::test_cloud_reaper_writes_checkrun_kind_aws_reaper, and
    ::test_multipass_reaper_unchanged_no_boto3.
    """
    from test_cloud_reaper import (
        test_cloud_reaper_respects_allowlist_and_purpose_test,
        test_cloud_reaper_writes_checkrun_kind_aws_reaper,
        test_multipass_reaper_unchanged_no_boto3,
    )

    test_cloud_reaper_respects_allowlist_and_purpose_test()
    test_cloud_reaper_writes_checkrun_kind_aws_reaper()
    test_multipass_reaper_unchanged_no_boto3()


@pytest.mark.django_db
def test_empty_allowlist_ref_and_default_chain_refuse(monkeypatch):
    """Empty allowlist / empty ref / default boto3 chain all refuse.

    Transcribes tests/test_aws_creds.py::test_empty_aws_credentials_ref_refuses,
    ::test_empty_allowlist_refuses_live, and
    ::test_explicit_keys_passed_into_client_never_default_chain.
    The honesty clauses also pin the demo record: no invented token env.
    """
    from test_aws_creds import (
        test_empty_allowlist_refuses_live,
        test_empty_aws_credentials_ref_refuses,
        test_explicit_keys_passed_into_client_never_default_chain,
    )

    test_empty_aws_credentials_ref_refuses()
    test_empty_allowlist_refuses_live()
    test_explicit_keys_passed_into_client_never_default_chain(monkeypatch)

    record = _assert_honest_t1_demo()
    assert "HUB_TEST_AWS_ACCOUNT_IDS" in record
    assert "HUB_TEST_AWS_REGIONS" in record


def test_nav_stays_six():
    """NAV is still six. VALID_TIERS stays {t1, t2, t3}. conformance-5
    excludes t2/t3. Demo names the MUST path.

    Transcribes tests/test_aws_creds.py::test_nav_still_six,
    tests/test_image_registry.py::test_nav_still_six,
    tests/test_conformance_gate.py::test_valid_tiers_still_t1_t2_t3_only, and
    tests/test_makefile_nightly.py::test_conformance_5_is_phase_5_minus_live_tiers.
    """
    import check
    import gates

    src = (REPO / "frontend" / "src" / "Chrome.jsx").read_text(encoding="utf-8")
    start = src.index("export const NAV = [")
    end = src.index("];", start)
    ids = re.findall(r'id:\s*"(\w+)"', src[start:end])
    assert ids == NAV_IDS

    assert check.VALID_TIERS == {"t1", "t2", "t3"}
    assert "t4" not in check.VALID_TIERS

    recipe = gates.recipe(REPO, "conformance-5")
    assert recipe, "Makefile has no `conformance-5` recipe"
    assert "--phase 5" in recipe
    assert "--exclude-tier t2" in recipe
    assert "--exclude-tier t3" in recipe
    recipe3 = gates.recipe(REPO, "conformance-3")
    assert "--phase 3" in recipe3
    assert "--exclude-tier" not in recipe3

    demo_req = _registry()["P5-AWS-DEMO"]
    assert demo_req["verify"] == "demo"
    assert "conformance/demos/phase-5.md" in demo_req.get("demo", [])

    dns01 = _waiver_lines(DNS01_ID)
    assert dns01, f"{DNS01_ID} must stay waived — named first slip"
    assert "first slip" in dns01[0].lower() or "DNS-01" in dns01[0]
    sec = _waiver_lines(FULL_TEXT_SEC_B2)
    assert sec, f"{FULL_TEXT_SEC_B2} must stay waived — DNS-01 is unbuilt"
    assert WAIVER_24H in _waivers()

    record = _assert_honest_t1_demo()
    assert "conformance-3" in record.lower()
    assert "all-tiers" in record.lower() or "all tiers" in record.lower()
    eval_doc = (REPO / "docs" / "ssh-ca-evaluation.md").read_text(encoding="utf-8")
    assert "do **not** enable" in eval_doc.lower() or "does not enable" in eval_doc.lower()
    assert "docs/ssh-ca-evaluation.md" in record
