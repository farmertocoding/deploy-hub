"""Shared Ed25519 vectors vs intake verifier and Hub re-verifier (Q9 / K2).

Both implementations load conformance/fixtures/partner-signature-vectors.json
and must not share a module. Hub refuse wins on quota-exceeded. Replay is
rejected at the Hub even when Fake intake forwards. T1 tests may import intake.
Do not mark PART-Q9-T2-CONTAINER or PART-Q9-T3-LIVE-PATH.
"""
import ast
import base64
import json
import pathlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.test import override_settings

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
VECTORS_PATH = REPO / "conformance" / "fixtures" / "partner-signature-vectors.json"
FORBIDDEN_MARKS = {"PART-Q9-T2-CONTAINER", "PART-Q9-T3-LIVE-PATH"}
SECRET_NEEDLES = (
    "whsec_",
    "BEGIN PRIVATE",
    "BEGIN OPENSSH PRIVATE",
    "hubk_",
)


def _vectors():
    assert VECTORS_PATH.is_file(), "shared vector file is missing"
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _pub(vectors):
    raw = base64.b64decode(vectors["public_key_raw_b64"].encode("ascii"), validate=True)
    return Ed25519PublicKey.from_public_bytes(raw)


def _intake_keys(vectors):
    return {vectors["key_id"]: _pub(vectors)}


def _partner(vectors, slug):
    from core.models import Partner

    return Partner.objects.create(
        slug=slug,
        name=slug,
        pubkey_current=vectors["public_key_raw_b64"],
    )


def _fill_quota(partner, n):
    from core.models import PartnerSite, Project, Site

    for i in range(n):
        name = f"{partner.slug}-s{i}"
        project = Project.objects.create(name=name, slug=name)
        site = Site.objects.create(
            project=project,
            name=name,
            exposure=Site.Exposure.MESH_ONLY,
        )
        PartnerSite.objects.create(
            partner=partner, site=site, tenant_ref=f"tenant-{i}",
        )


def _surfaces():
    from core.models import AuditEvent, CheckRun, Finding

    blobs = []
    for row in Finding.objects.all():
        blobs.extend([
            row.title, row.body, row.fix_action, row.entity,
            row.fingerprint, row.severity, row.source_engine,
        ])
    for event in AuditEvent.objects.all():
        blobs.extend([event.action, event.detail, event.object_type, event.object_id])
    for run in CheckRun.objects.all():
        blobs.extend([run.kind, run.status, run.results])
    return json.dumps(blobs, default=str)


def _job(case, partner, job_id):
    return {
        "id": job_id,
        "type": "partner-job",
        "partner_pk": partner.pk,
        "method": case["method"],
        "path": case["path"],
        "body": case["body"],
        "headers": dict(case["headers"]),
    }


def _assert_no_live_q9_marks(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "req"):
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and arg0.value in FORBIDDEN_MARKS:
            found.append(arg0.value)
    assert found == [], f"T1 vector tests must not mark live Q9 ids: {found}"


@pytest.mark.req("PART-Q9-SHARED-VECTORS")
def test_vectors_valid_passes_both_verifiers():
    """A valid signed vector authenticates at intake and at Hub re-verify.

    What would make this fail: a Hub-only suite, a second vector file, or
    either verifier rejecting a canonical C4 signature inside the window.
    """
    from core.partner_verify import load_shared_vectors as hub_load
    from core.partner_verify import reverify
    from intake.verify import load_shared_vectors as intake_load
    from intake.verify import verify as intake_verify

    vectors = _vectors()
    case = vectors["cases"]["valid"]
    assert intake_load()["cases"]["valid"]
    assert hub_load()["cases"]["valid"]
    intake_verify(
        case["method"], case["path"], case["body"], case["headers"],
        _intake_keys(vectors), now=vectors["now"],
    )
    result = reverify(
        _partner(vectors, "vec-valid"),
        case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    assert result.ok is True
    _assert_no_live_q9_marks(pathlib.Path(__file__))


@pytest.mark.req("PART-Q9-SHARED-VECTORS")
def test_vectors_expired_rejected_by_both():
    """Timestamp outside the 5-minute window is rejected by both verifiers.

    What would make this fail: Hub-only window checks, or intake treating an
    expired vector as authenticated.
    """
    from core.partner_verify import SignatureRejected as HubRejected
    from core.partner_verify import reverify
    from intake.verify import SignatureRejected as IntakeRejected
    from intake.verify import verify as intake_verify

    vectors = _vectors()
    case = vectors["cases"]["expired"]
    with pytest.raises(IntakeRejected):
        intake_verify(
            case["method"], case["path"], case["body"], case["headers"],
            _intake_keys(vectors), now=vectors["now"],
        )
    with pytest.raises(HubRejected):
        reverify(
            _partner(vectors, "vec-expired"),
            case["method"], case["path"], case["body"], case["headers"],
            now=vectors["now"],
        )


@pytest.mark.req("PART-Q9-SHARED-VECTORS")
def test_vectors_mutated_body_rejected_by_both():
    """A body that does not match the signed digest is rejected by both.

    What would make this fail: hashing a cached original body, or skipping
    sha256(body) so a mutated JSON still verifies.
    """
    from core.partner_verify import SignatureRejected as HubRejected
    from core.partner_verify import reverify
    from intake.verify import SignatureRejected as IntakeRejected
    from intake.verify import verify as intake_verify

    vectors = _vectors()
    case = vectors["cases"]["mutated-body"]
    with pytest.raises(IntakeRejected):
        intake_verify(
            case["method"], case["path"], case["body"], case["headers"],
            _intake_keys(vectors), now=vectors["now"],
        )
    with pytest.raises(HubRejected):
        reverify(
            _partner(vectors, "vec-mutated"),
            case["method"], case["path"], case["body"], case["headers"],
            now=vectors["now"],
        )


@pytest.mark.req("PART-K2-REPLAY-AT-HUB")
def test_vectors_replay_rejected_by_hub_even_if_intake_forwards():
    """Hub rejects a replayed nonce even when Fake intake forwards the job.

    What would make this fail: trusting intake's allow, skipping the Postgres
    nonce cache, or treating two copies in one FakeIntakeClient fetch as two
    new jobs.
    """
    from core.models import Finding
    from core.partner_verify import ReplayRejected, reverify
    from intake.verify import verify as intake_verify
    from monitor.intake_poll import FakeIntakeClient, poll

    vectors = _vectors()
    case = vectors["cases"]["replayed"]
    partner = _partner(vectors, "vec-replay")
    intake_verify(
        case["method"], case["path"], case["body"], case["headers"],
        _intake_keys(vectors), now=vectors["now"],
    )
    first = reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    assert first.ok is True
    intake_verify(
        case["method"], case["path"], case["body"], case["headers"],
        _intake_keys(vectors), now=vectors["now"],
    )
    job_a = _job(case, partner, "job_replay_a")
    job_b = _job(case, partner, "job_replay_b")
    client = FakeIntakeClient(items=[job_a, job_b])
    with override_settings(INTAKE_URL="http://intake.test"):
        poll(client=client, now=vectors["now"], jitter=0, sleep=lambda _s: None)
    with pytest.raises(ReplayRejected):
        reverify(
            partner, case["method"], case["path"], case["body"], case["headers"],
            now=vectors["now"],
        )
    row = Finding.objects.get(fingerprint=f"partner-replay:{partner.pk}")
    assert row.severity == "p2"
    assert row.fingerprint == f"partner-replay:{partner.pk}"


@pytest.mark.req("PART-Q9-SHARED-VECTORS")
def test_vectors_quota_exceeded_hub_authoritative():
    """Both verifiers load the quota-exceeded vector; Hub refuse wins.

    What would make this fail: skipping the case in either loader, or letting
    intake's allow override Hub when max_sites is already full.
    """
    from core.partner_verify import load_shared_vectors as hub_load
    from core.partner_verify import reverify
    from intake.verify import load_shared_vectors as intake_load
    from intake.verify import verify as intake_verify

    vectors = _vectors()
    case = vectors["cases"]["quota-exceeded"]
    intake_cases = intake_load()["cases"]
    hub_cases = hub_load()["cases"]
    assert "quota-exceeded" in intake_cases
    assert "quota-exceeded" in hub_cases
    partner = _partner(vectors, "vec-quota")
    _fill_quota(partner, partner.max_sites)
    intake_verify(
        case["method"], case["path"], case["body"], case["headers"],
        _intake_keys(vectors), now=vectors["now"],
    )
    result = reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    assert result.ok is False
    assert result.reason == "quota"


@pytest.mark.req("PART-Q9-SHARED-VECTORS")
def test_idempotency_match_returns_first_response():
    """Same Idempotency-Key and params within 24 h return the stored response.

    What would make this fail: treating the retry as a new write, or requiring
    the same nonce so a Stripe-style retry is classified as replay.
    """
    from core.partner_verify import reverify

    vectors = _vectors()
    case = vectors["cases"]["idempotency-match"]
    partner = _partner(vectors, "vec-idem-match")
    first = reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    assert first.ok is True
    retry = reverify(
        partner, case["method"], case["path"], case["body"], case["retry_headers"],
        now=vectors["now"],
    )
    assert retry.ok is True
    assert retry.status == first.status
    assert retry.response == first.response


@pytest.mark.req("PART-Q9-SHARED-VECTORS")
def test_idempotency_mismatch_is_422():
    """Same Idempotency-Key with different params is 422.

    What would make this fail: overwriting the stored response, or returning
    200 for a param mismatch.
    """
    from core.partner_verify import reverify

    vectors = _vectors()
    case = vectors["cases"]["idempotency-mismatch"]
    partner = _partner(vectors, "vec-idem-mis")
    first = reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    assert first.ok is True
    retry = reverify(
        partner, case["method"], case["path"], case["retry_body"],
        case["retry_headers"], now=vectors["now"],
    )
    assert retry.ok is False
    assert retry.status == 422


@pytest.mark.req("PART-K2-REPLAY-AT-HUB")
def test_finding_fingerprint_is_partner_replay_partner_pk():
    """C12 fingerprint is partner-replay:{partner.pk}, not the default kind:entity.

    What would make this fail: omitting fingerprint= so raise_alert defaults to
    partner-replay:partner:{pk}.
    """
    from core.models import Finding
    from core.partner_verify import ReplayRejected, reverify

    vectors = _vectors()
    case = vectors["cases"]["replayed"]
    partner = _partner(vectors, "vec-fp")
    reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    with pytest.raises(ReplayRejected):
        reverify(
            partner, case["method"], case["path"], case["body"], case["headers"],
            now=vectors["now"],
        )
    fp = f"partner-replay:{partner.pk}"
    row = Finding.objects.get(fingerprint=fp)
    assert row.fingerprint == fp
    assert row.fingerprint != f"partner-replay:partner:{partner.pk}"
    assert not Finding.objects.filter(
        fingerprint=f"partner-replay:partner:{partner.pk}",
    ).exists()


def test_no_whsec_or_private_key_in_finding_detail():
    """Replay Finding / AuditEvent / CheckRun never carry whsec_, hubk_, or PEM.

    What would make this fail: putting X-Partner-Key-Id or a private key seed
    into title/body/detail.
    """
    from core.partner_verify import ReplayRejected, reverify

    vectors = _vectors()
    case = vectors["cases"]["replayed"]
    partner = _partner(vectors, "vec-secret")
    reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    with pytest.raises(ReplayRejected):
        reverify(
            partner, case["method"], case["path"], case["body"], case["headers"],
            now=vectors["now"],
        )
    blob = _surfaces()
    for needle in SECRET_NEEDLES:
        assert needle not in blob, needle


def test_verifiers_do_not_share_a_module():
    """intake/verify.py and core/partner_verify.py are independent implementations.

    What would make this fail: Hub importing intake.verify, intake importing
    core.partner_verify, or both delegating canonical_string to a shared helper.
    """
    hub = REPO / "core" / "partner_verify.py"
    edge = REPO / "intake" / "verify.py"
    assert hub.is_file()
    assert edge.is_file()
    assert hub.read_text(encoding="utf-8") != edge.read_text(encoding="utf-8")

    def imported(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    hub_imps = imported(hub)
    edge_imps = imported(edge)
    assert "intake" not in hub_imps
    assert "core" not in edge_imps
    assert "partner_verify" not in edge_imps
    first_party = {
        "core", "intake", "monitor", "hub", "deploys", "vault", "wizard",
        "providers", "provision", "catalog", "scanner", "realtime",
        "reconcile", "scaling",
    }
    shared = (hub_imps & edge_imps) & first_party
    assert not shared, f"verifiers share first-party modules: {shared}"
