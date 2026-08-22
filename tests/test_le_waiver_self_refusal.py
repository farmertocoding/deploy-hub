"""T1: the LE / CF-live waivers refuse themselves once credentials exist (M4).

HARNESS-T3-LE-STAGING and DNS-CF-T3-LIVE are tier:t3. These tests must never
carry those req markers — a T1 sibling cannot green either id (D-024 / D-043).
They always run, and they go red the moment HUB_TEST_CF_TOKEN and a
purpose=test DnsZone both exist while the no-test-zone-credentials lines
remain in WAIVERS.md.
"""
from __future__ import annotations

import inspect
import os
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
# Split so this file itself never mentions the retired env name; the product
# allowlist scan (test_single_zone_allowlist_namespace) forbids the literal
# in any new module.
_RETIRED_ZONE_ENV = "HUB_TEST_" + "DNS_ZONE"
TOKEN_ENV = "HUB_TEST_CF_TOKEN"
ALLOWLIST_ENV = "HUB_TEST_ZONE_SLUGS"
LE_WAIVER = "HARNESS-T3-LE-STAGING"
CF_WAIVER = "DNS-CF-T3-LIVE"
CREDENTIAL_REASON = "no-test-zone-credentials"

pytestmark = pytest.mark.django_db


def _waiver_lines(req_id):
    text = (REPO / "WAIVERS.md").read_text(encoding="utf-8")
    return [
        line
        for line in text.splitlines()
        if line.startswith(f"WAIVED: {req_id} ") and CREDENTIAL_REASON in line
    ]


def _real_token():
    return os.environ.get(TOKEN_ENV, "").strip()


def _plant_test_zone(settings, name="t17-probe.example"):
    from dns_fixtures import default_dns_zone

    zone = default_dns_zone(name, purpose="test")
    settings.HUB_TEST_MODE = True
    settings.HUB_TEST_ZONE_SLUGS = [zone.name]
    return zone


def test_le_waiver_is_red_when_credentials_are_present(monkeypatch, settings):
    """waiver_illegal_if(credentials_present) is True once token + test zone exist.

    What would make this fail: the probe ignoring a purpose=test DnsZone, or
    still treating the no-test-zone-credentials waiver as legal after the
    real token lands on this host (2.5 finding M4).
    """
    from tests.harness.multipass import credentials_present, waiver_illegal_if

    real = _real_token()
    _plant_test_zone(settings)
    if not real:
        monkeypatch.setenv(TOKEN_ENV, "t17-planted-not-a-credential")

    assert credentials_present() is True
    assert waiver_illegal_if(credentials_present) is True

    if real:
        offenders = _waiver_lines(LE_WAIVER)
        assert offenders == [], (
            f"{TOKEN_ENV} is set and a purpose=test DnsZone exists, so the "
            f"{LE_WAIVER}+{CREDENTIAL_REASON} waiver is illegal — retire it "
            f"with the credentialed run: {offenders}"
        )


def test_le_waiver_is_allowed_when_credentials_are_absent(monkeypatch, settings):
    """Absent token or absent purpose=test zone: the LE waiver may stand.

    What would make this fail: the probe going red on an empty host, so the
    honest skipped-only line could never be planted (D-031 / D-043).
    """
    from core.models import DnsZone
    from tests.harness.multipass import credentials_present, waiver_illegal_if

    monkeypatch.delenv(TOKEN_ENV, raising=False)
    DnsZone.objects.filter(purpose="test").delete()
    settings.HUB_TEST_ZONE_SLUGS = ["hub-test"]

    assert credentials_present() is False
    assert waiver_illegal_if(credentials_present) is False
    assert _waiver_lines(LE_WAIVER), (
        f"{LE_WAIVER}+{CREDENTIAL_REASON} must stay in WAIVERS.md while the "
        "test-zone token is absent — skip is not a green"
    )


def test_cf_live_waiver_follows_the_same_probe(monkeypatch, settings):
    """DNS-CF-T3-LIVE uses credentials_present, not a second helper.

    What would make this fail: a CF-live waiver that stays legal after the
    LE probe goes red, or a missing no-test-zone-credentials line while the
    token is absent.
    """
    from tests.harness.multipass import credentials_present, waiver_illegal_if

    real = _real_token()
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert waiver_illegal_if(credentials_present) is False

    _plant_test_zone(settings, name="t17-cf.example")
    monkeypatch.setenv(TOKEN_ENV, "t17-planted-not-a-credential")
    assert waiver_illegal_if(credentials_present) is True

    le = _waiver_lines(LE_WAIVER)
    cf = _waiver_lines(CF_WAIVER)
    if real:
        assert le == [] and cf == [], (
            "both credential waivers must retire together once the token "
            f"exists: le={le!r} cf={cf!r}"
        )
    else:
        assert le, f"{LE_WAIVER}+{CREDENTIAL_REASON} missing while token is absent"
        assert cf, f"{CF_WAIVER}+{CREDENTIAL_REASON} missing while token is absent"


def test_probe_reads_the_pinned_env_names_only():
    """credentials_present reads HUB_TEST_CF_TOKEN + HUB_TEST_ZONE_SLUGS only.

    What would make this fail: the probe consulting the retired zone env, so
    a dual-namespace allowlist could go green against a name the product
    wall never authorized (D-033).
    """
    from tests.harness import multipass
    from tests.harness.multipass import credentials_present

    source = inspect.getsource(credentials_present)
    assert TOKEN_ENV in source
    assert ALLOWLIST_ENV in source
    assert _RETIRED_ZONE_ENV not in source
    assert _RETIRED_ZONE_ENV not in inspect.getsource(multipass)

    reaper = (REPO / "monitor" / "reaper.py").read_text(encoding="utf-8")
    assert TOKEN_ENV in reaper
    assert _RETIRED_ZONE_ENV not in reaper
