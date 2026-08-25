"""Phase 7 acceptance — each test transcribes one design-note §4 clause.

`check.py --phase 7 --exclude-tier t2 --exclude-tier t3` is the phase-7 gate.
Everyday `conformance` / `review-round` stay `--phase 5`. T1 inject only:
`restore_to_clean=` never live docker. Do not invent HUB_TEST_* /
HUB_INTAKE_HMAC / HUB_WEBHOOK_SECRET. Do not add Playwright. Do not stub
named-partner.md. Do not mark P7-RESTORE-DEMO or P7-ROUTER-DEMO on pytest.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "conformance" / "demos" / "phase-7.md"
NAMED_PARTNER = REPO / "conformance" / "demos" / "named-partner.md"
NAV_IDS = ["home", "sites", "targets", "deploys", "findings", "settings"]
NAMED = (
    "test_restore_into_clean_container_t1",
    "test_restore_command_block_remains",
    "test_nav_stays_six",
    "test_demo_does_not_claim_live_docker_or_kek",
    "test_tunnel_nothing_forwarded_files_and_resolves",
    "test_router_advice_target_tab",
)

pytestmark = [pytest.mark.acceptance(phase=7)]


@pytest.fixture
def auth_client(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(
        username="op", password="pw-1234567890",
    )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    from provision import backup as backup_mod

    store = tmp_path / "backups"
    store.mkdir()
    monkeypatch.setattr(backup_mod, "BACKUP_STORE_DIR", store, raising=False)
    return store


def _demo():
    assert DEMO.is_file() and DEMO.stat().st_size > 0, (
        "conformance/demos/phase-7.md must exist — P7-RESTORE-DEMO is verify: demo"
    )
    text = DEMO.read_text(encoding="utf-8")
    assert text.strip(), "a whitespace-only demo is not a record"
    return text


def _registry():
    data = yaml.safe_load(
        (REPO / "conformance" / "requirements.yaml").read_text(encoding="utf-8"),
    )
    return {r["id"]: r for r in data["requirements"]}


def _assert_honest_t1_demo():
    record = _demo()
    lower = record.lower()
    for name in NAMED:
        assert name in record, f"demo must name the acceptance nodeid {name}"
    assert "restore_to_clean" in record
    assert "t1" in lower
    assert "no live" in lower or "not a live" in lower
    assert "playwright" not in lower or "no playwright" in lower
    assert "HUB_TEST_" + "AWS_TOKEN" not in record
    assert "HUB_TEST_" + "CF_TOKEN" not in record
    assert "HUB_INTAKE_" + "HMAC" not in record
    assert "HUB_WEBHOOK_" + "SECRET" not in record
    assert "stub" not in lower
    assert "todo" not in lower
    assert "conformance-7" in lower
    assert "--exclude-tier t2" in record and "--exclude-tier t3" in record
    assert "P7-RESTORE-DEMO" in record
    assert "§4" in record or "section 4" in lower
    assert "named-partner.md" in record
    assert "uncovered" in lower
    assert "BACKUP_KEY" in record
    assert "kek" in lower
    assert not NAMED_PARTNER.exists(), (
        "conformance/demos/named-partner.md must stay absent — a filler "
        "would verify PART-U1-NAMED-PARTNER and invent a partner"
    )
    return record


@pytest.mark.django_db
@pytest.mark.req("BACKUP-RESTORE-CLEAN-T1")
def test_restore_into_clean_container_t1(client, backup_dir, monkeypatch):
    """Sealed dump, T1 touch + type-the-name, injected restore_to_clean → 201.
    RESTORE_CLEAN metadata has unit_id and checkrun_pk; no dump bytes;
    live SiteInstance untouched. Wrong confirm and missing dump → 4xx.

    Transcribes tests/test_backup_operator.py::
    test_restore_to_clean_unseals_chosen_dump_with_backup_key and
    ::test_restore_http_is_t1_type_the_site_name.
    """
    from test_backup_operator import (
        test_restore_http_is_t1_type_the_site_name,
        test_restore_to_clean_unseals_chosen_dump_with_backup_key,
    )

    test_restore_to_clean_unseals_chosen_dump_with_backup_key(backup_dir)
    test_restore_http_is_t1_type_the_site_name(client, backup_dir, monkeypatch)


@pytest.mark.django_db
@pytest.mark.req("BACKUP-RESTORE-COMMAND-REMAINS")
def test_restore_command_block_remains(auth_client, backup_dir):
    """GET list still returns restore_command; BackupPanel still renders <pre>.

    Transcribes tests/test_backup_operator.py::
    test_restore_is_command_block_not_a_post.
    """
    from test_backup_operator import test_restore_is_command_block_not_a_post

    test_restore_is_command_block_not_a_post(auth_client, backup_dir)


@pytest.mark.django_db
def test_nav_stays_six():
    """NAV is still six. VALID_TIERS stays {t1, t2, t3}. conformance-7
    excludes t2/t3. Everyday conformance stays phase 5. Demo names §4.
    """
    import check
    import gates
    from test_sites_single_instance import test_nav_stays_six as _nav

    _nav()
    src = (REPO / "frontend" / "src" / "Chrome.jsx").read_text(encoding="utf-8")
    start = src.index("export const NAV = [")
    end = src.index("];", start)
    ids = re.findall(r'id:\s*"(\w+)"', src[start:end])
    assert ids == NAV_IDS

    assert check.VALID_TIERS == {"t1", "t2", "t3"}
    assert "t4" not in check.VALID_TIERS

    recipe = gates.recipe(REPO, "conformance-7")
    assert recipe, "Makefile has no `conformance-7` recipe"
    assert "--phase 7" in recipe
    assert "--exclude-tier t2" in recipe
    assert "--exclude-tier t3" in recipe
    everyday = gates.recipe(REPO, "conformance")
    assert "--phase 5" in everyday
    assert "--phase 7" not in everyday

    demo_req = _registry()["P7-RESTORE-DEMO"]
    assert demo_req["verify"] == "demo"
    assert "conformance/demos/phase-7.md" in demo_req.get("demo", [])
    router_demo = _registry()["P7-ROUTER-DEMO"]
    assert router_demo["verify"] == "demo"
    assert "conformance/demos/phase-7.md" in router_demo.get("demo", [])
    u1 = _registry()["PART-U1-NAMED-PARTNER"]
    assert u1["verify"] == "demo"
    assert "conformance/demos/named-partner.md" in u1.get("demo", [])

    record = _assert_honest_t1_demo()
    assert "conformance-5" in record.lower() or "phase 5" in record.lower()
    assert "P7-ROUTER-DEMO" in record
    assert "wan_probe" in record
    assert "router-forwarded" in record
    assert "Probe router" in record
    assert "Hardening" in record and "Router" in record
    lower = record.lower()
    assert "no live upnp" in lower
    assert "no live wan" in lower
    assert "model-tailored" in lower
    assert "no preview" in lower or "preview" in lower
    assert "lan" in lower
    assert "pulumi" in lower
    assert "azure" in lower


def test_demo_does_not_claim_live_docker_or_kek():
    """The record is T1 inject only: no live docker overwrite, no KEK, no U1.

    Transcribes the honesty contract of design note §4 / P7-RESTORE-DEMO.
    """
    record = _assert_honest_t1_demo()
    lower = record.lower()
    assert "live docker" in lower or "no live docker" in lower
    assert "does not claim" in lower or "does **not** claim" in lower
    assert "did not run" in lower or "this session did not" in lower
    assert not NAMED_PARTNER.exists()


@pytest.mark.django_db
@pytest.mark.req("ROUTER-TUNNEL-NOTHING-FORWARDED")
def test_tunnel_nothing_forwarded_files_and_resolves():
    """Tunnel target + injected wan_probe files then resolves
    router-forwarded:{pk}. Missing inject and non-tunnel skip.

    Transcribes tests/test_router_advisor.py::
    test_tunnel_forward_files_finding,
    ::test_empty_forwards_resolves_finding,
    ::test_missing_wan_probe_does_not_file,
    and ::test_non_tunnel_skips.
    """
    from test_router_advisor import (
        test_empty_forwards_resolves_finding,
        test_missing_wan_probe_does_not_file,
        test_non_tunnel_skips,
        test_tunnel_forward_files_finding,
    )

    test_tunnel_forward_files_finding()
    test_empty_forwards_resolves_finding()
    test_missing_wan_probe_does_not_file()
    test_non_tunnel_skips()


@pytest.mark.django_db
@pytest.mark.req("ROUTER-ADVICE-TARGET-TAB")
def test_router_advice_target_tab(client, monkeypatch):
    """GET detail router_advice; T3 Probe router empty forwards
    resolves; missing inject and non-tunnel POST are 4xx.

    Transcribes tests/test_router_advisor.py::
    test_target_detail_returns_router_advice,
    ::test_probe_http_t3_empty_forwards_resolves,
    ::test_probe_http_missing_inject_is_4xx,
    and ::test_probe_http_non_tunnel_is_4xx.
    """
    from test_router_advisor import (
        test_probe_http_missing_inject_is_4xx,
        test_probe_http_non_tunnel_is_4xx,
        test_probe_http_t3_empty_forwards_resolves,
        test_target_detail_returns_router_advice,
    )

    test_target_detail_returns_router_advice(client)
    test_probe_http_t3_empty_forwards_resolves(client, monkeypatch)
    test_probe_http_missing_inject_is_4xx(client, monkeypatch)
    test_probe_http_non_tunnel_is_4xx(client, monkeypatch)
