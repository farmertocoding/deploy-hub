"""Phase 6 Sites chrome: scale_ready payload, list-row single-instance-only, F8.

UX-P6-SINGLE-INSTANCE. Live project_row_body always emits scale_ready as a real
bool and does not alias single_instance = not scale_ready. SiteObserved paints
single-instance-only iff scale_ready === false and is shown on Sites list rows.
F8 REQUIRED_STATE_IDS includes single-instance-only and scale-out-proposal.
NAV stays six. Markers on def test_* only (C11).
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest
from dns_fixtures import default_dns_zone

from core.models import Project, Site

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
TITLE = "Scale-out proposal awaiting approval (propose mode)"
FIX_ACTION = "Ack is not launch. Propose-mode does not launch."
ALLOWED_INSTANCE_TOKENS = ("single-instance-only", "single-instance")


@pytest.fixture
def auth_client(client, django_user_model):
    """Logged-in operator with a confirmed second factor."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


def _frontend(*parts):
    return (REPO / "frontend").joinpath(*parts).read_text(encoding="utf-8")


def _seed():
    return json.loads((REPO / "simulation" / "seed_v1.json").read_text(encoding="utf-8"))


def _required_state_ids():
    src = _frontend("tests", "simulation-states.test.ts")
    block = src.split("const REQUIRED_STATE_IDS = [", 1)[1].split("];", 1)[0]
    return re.findall(r'"([^"]+)"', block)


def _nav_ids():
    block = _frontend("src", "Chrome.jsx").split("export const NAV = [", 1)[1].split("];", 1)[0]
    return re.findall(r'id:\s*"([^"]+)"', block)


def _strip_allowed_instance_tokens(text):
    for token in ALLOWED_INSTANCE_TOKENS:
        text = text.replace(token, "")
    return text


def _full_instance_tokens(text):
    """Whole tokens only — 'single-instance' is not a prefix include of -only."""
    return set(re.findall(r"single-instance(?:-only)?", text))


@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_project_row_emits_scale_ready_false_without_aliasing_single_instance(auth_client):
    """Live rows always emit scale_ready as a real bool; do not alias one-copy.

    scale_ready False present; single_instance is not True-because-of-that
    (omit or false-from-count, never `not scale_ready`).
    """
    project = Project.objects.create(name="not-ready", slug="not-ready")
    cold = Site.objects.create(
        project=project,
        name="sqlite-lab",
        domain="sqlite.example.test",
        dns_zone=default_dns_zone("sqlite.example.test"),
    )
    hot = Site.objects.create(
        project=project,
        name="ready-shop",
        domain="ready.example.test",
        dns_zone=default_dns_zone("ready.example.test"),
        scale_ready=True,
    )
    assert cold.scale_ready is False
    assert hot.scale_ready is True

    listed = next(
        p for p in auth_client.get("/api/v1/projects/").json()
        if p["slug"] == "not-ready"
    )
    by_name = {row["name"]: row for row in listed["sites"]}
    cold_row = by_name["sqlite-lab"]
    hot_row = by_name["ready-shop"]

    assert "scale_ready" in cold_row, "live site row omitted scale_ready"
    assert cold_row["scale_ready"] is False
    assert type(cold_row["scale_ready"]) is bool
    assert cold_row.get("single_instance") is not True

    assert "scale_ready" in hot_row
    assert hot_row["scale_ready"] is True
    assert type(hot_row["scale_ready"]) is bool
    assert hot_row.get("single_instance") is not True

    views = (REPO / "wizard" / "views.py").read_text(encoding="utf-8")
    body = views.split("def project_row_body", 1)[1].split("\nclass ", 1)[0]
    assert "scale_ready" in body
    assert "not scale_ready" not in body
    assert "not site.scale_ready" not in body
    serializer = views.split("class SiteSummarySerializer", 1)[1].split(
        "class ProjectSummarySerializer", 1
    )[0]
    assert "scale_ready" in serializer
    assert "required=False" in serializer


@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_site_observed_source_paints_single_instance_only_iff_scale_ready_false():
    """grep Sites.jsx: scale_ready === false → single-instance-only.

    SiteObserved used on list rows (SitesView maps it). Omitted/undefined must
    not paint — not `if (!site.scale_ready)`.
    """
    src = _frontend("src", "screens", "Sites.jsx")
    observed = src.split("export function SiteObserved", 1)[1].split("export function", 1)[0]
    assert "scale_ready === false" in observed
    assert "single-instance-only" in observed
    assert "!site.scale_ready" not in observed
    view = src.split("export function SitesView", 1)[1].split("export default function", 1)[0]
    assert "<SiteObserved" in view
    assert "PartnerBadge" in view
    assert "ManifestLine" in view


@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_f8_required_ids_include_single_instance_only_and_scale_out_proposal():
    """grep REQUIRED_STATE_IDS — both F8 ids, with seed rows to match."""
    ids = _required_state_ids()
    assert "single-instance-only" in ids
    assert "scale-out-proposal" in ids
    seed_ids = [row["id"] for row in _seed()["states"]]
    assert "single-instance-only" in seed_ids
    assert "scale-out-proposal" in seed_ids


@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
def test_f8_required_ids_include_scale_cheap_remediation():
    """F8 seed for cheap remediations: title, three steps, no Approve/Launch."""
    ids = _required_state_ids()
    assert "scale-cheap-remediation" in ids
    state = next(row for row in _seed()["states"] if row["id"] == "scale-cheap-remediation")
    finding = state.get("finding") or {}
    blob = json.dumps(state)
    stripped = _strip_allowed_instance_tokens(blob)
    assert re.search(r"\binstance\b", stripped, re.I) is None
    assert finding.get("title") == "Cheap remediations before overflow (propose mode)"
    assert finding.get("fix_action") == (
        "Ack is not launch. Apply cache and workers before overflow."
    )
    body = finding.get("body") or ""
    assert "Cache-Control" in body
    assert "Cloudflare cache" in body
    assert "gunicorn" in body
    assert "2×CPU+1" in body
    assert "propose-mode does not launch" in body
    assert re.search(r"\bApprove\b", blob) is None
    assert re.search(r"\bLaunch\b", blob) is None
    assert "Create target" not in blob


@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_nav_stays_six():
    """NAV stays the six object-centric items. No Scale / Overflow / Instances."""
    ids = _nav_ids()
    assert ids == ["home", "sites", "targets", "deploys", "findings", "settings"]
    assert len(ids) == 6
    lowered = {item.lower() for item in ids}
    assert "scale" not in lowered
    assert "overflow" not in lowered
    assert "instances" not in lowered
    sim = _frontend("tests", "simulation-states.test.ts")
    assert "NAV.length, 6" in sim


@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_scale_out_proposal_markup_has_no_instance_word_or_approve_control():
    """seed/finding copy after stripping allowed tokens; no Approve/Launch control."""
    state = next(row for row in _seed()["states"] if row["id"] == "scale-out-proposal")
    finding = state.get("finding") or {}
    blob = json.dumps(state)
    stripped = _strip_allowed_instance_tokens(blob)
    assert re.search(r"\binstance\b", stripped, re.I) is None
    assert finding.get("title") == TITLE
    assert finding.get("fix_action") == FIX_ACTION
    assert finding.get("severity") == "p2"
    body = finding.get("body") or ""
    assert "0.0416" in body
    assert "t3.medium" in body
    assert "propose-mode does not launch" in body
    assert re.search(r"\bApprove\b", blob) is None
    assert re.search(r"\bLaunch\b", blob) is None
    assert "Create target" not in blob
    assert "$0.05" not in blob
    render_src = _frontend("tests", "simulation-states.test.ts").split("const RENDER", 1)[1]
    chunk = render_src.split('"scale-out-proposal":', 1)[1][:800]
    assert "ActionButton" not in chunk
    assert "T1Overlay" not in chunk
    assert "Create target" not in chunk


@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_f8_single_instance_seed_does_not_retint_to_single_instance_only():
    """single-instance as a full token; doesNotMatch /single-instance-only/.

    Do not use prefix includes (substring trap).
    """
    state = next(row for row in _seed()["states"] if row["id"] == "single-instance")
    dumped = json.dumps(state)
    tokens = _full_instance_tokens(dumped)
    assert "single-instance" in tokens
    assert "single-instance-only" not in tokens
    must = state.get("must_render") or []
    assert "single-instance" in must
    assert "single-instance-only" not in must
    sim = _frontend("tests", "simulation-states.test.ts")
    assert "doesNotMatch" in sim
    assert r"/single-instance-only/" in sim
