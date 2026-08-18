"""What the HTTP API puts on the wire, as opposed to what its serializers return.

R18-SEC-1. Rounds 15-17 closed one class — repo-controlled text reaching a device that
interprets it — at the CLI's two exits, and wrote the rule into `scanner/presentation.py`.
The API is the third exit, and it had no such treatment: DRF's `JSONRenderer` renders with
`ensure_ascii=False` (settings' `UNICODE_JSON` defaults to True and nothing overrode it),
so a stored check detail went out as itself.

`curl`, `http`, `jq`, a CI job's log — the consumers of a JSON API are terminals at least
as often as they are parsers, which is the same argument that made `--json` a finding in
round 17. The React UI is unaffected for this class: `JSON.parse` yields a string that
React puts in a text node, and a text node interprets nothing.
"""
import json

import pytest

from core.models import Project
from scanner import core as scanner_core
from scanner import presentation

pytestmark = pytest.mark.django_db

# One member of each family the class covers, chosen so a failure names which family
# escaped: an 8-bit C1 control, a bidi override, a zero-width joiner-space, the BOM.
HOSTILE_NAME = ("src/na" + chr(0x9B) + "me" + chr(0x202E) + "gnp.exe"
                + chr(0x200B) + chr(0xFEFF) + ".ts")


@pytest.fixture
def auth_client(client, django_user_model):
    """A logged-in operator WITH a confirmed second factor.

    `EnrollmentRequiredMiddleware` (§6.10) fail-closes every `/api/` path for a user who
    has not enrolled, so a session alone reaches nothing — the same fixture
    tests/test_wizard.py carries, for the same reason.
    """
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


@pytest.fixture
def hostile_project():
    """A project whose STORED report carries the hostile name, the way a scan leaves it.

    The scanner is right to store the true bytes — a report that repaired the name would
    be lying about what it found — so the stored report is exactly what a scan of a
    repository with such a file produces, and the question is only what the API does with
    it on the way out.
    """
    return Project.objects.create(
        name="hostile", slug="hostile", git_url="https://github.com/o/r.git",
        scanned_at="2026-08-18T00:00:00Z",
        scan_report={
            "schema_version": scanner_core.SCHEMA_VERSION,
            "modules": ["dockerfile"],
            "checks": [{
                "id": "core.symlinked-files", "tier": "warning",
                "title": "Files linked out of the scanned repository were not read",
                "detail": f"1 symlinked file resolves outside:\n{HOSTILE_NAME}",
                "fix_hint": "", "execution": "static",
                "refused_paths": [HOSTILE_NAME],
            }],
            "sandbox_jobs": [], "wizard_questions": [],
            "manifest_draft": {}, "summary": {"warning": 1},
        })


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r18_sec_1_the_api_does_not_put_the_class_on_the_wire(auth_client,
                                                                    hostile_project):
    """R18-SEC-1 (medium): the third exit, unguarded.

    Measured before the fix, through Django's test client on the stored report above:

        /api/v1/projects/1/readiness/  status=200
            raw U+009B in response bytes: True
            raw U+202E in response bytes: True

    U+009B is the 8-bit CSI — the same control round 15 escaped for the CLI — and U+202E
    reorders everything printed after it. A response body is bytes on a terminal as often
    as it is an object in a parser.
    """
    response = auth_client.get(f"/api/v1/projects/{hostile_project.pk}/readiness/")

    assert response.status_code == 200
    assert not presentation._TEXT_CONTROL_RE.search(response.content.decode("utf-8")), (
        "repo-controlled text reached the wire raw")
    for codepoint in (0x9B, 0x202E, 0x200B, 0xFEFF):
        assert chr(codepoint).encode("utf-8") not in response.content, hex(codepoint)
        assert f"\\u{codepoint:04x}".encode() in response.content, (
            f"U+{codepoint:04X} is named nowhere in the response")


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r18_sec_1_the_parsed_body_is_byte_for_byte_the_stored_report(
        auth_client, hostile_project):
    """DATA-PRESERVING, which is what makes the UI claim assertable rather than asserted.

    `\\uXXXX` is a spelling, not a repair: a parser — `json.loads` here, `JSON.parse` in
    the browser — returns the identical code points, so the React UI renders exactly what
    it rendered before this commit, and a client that stores the report keeps the true
    bytes. If that were not true, escaping at the renderer would be a scanner lying about
    what it found, one layer further out.
    """
    response = auth_client.get(f"/api/v1/projects/{hostile_project.pk}/readiness/")
    body = json.loads(response.content.decode("utf-8"))

    check = body["warnings"][0]
    assert check["refused_paths"] == [HOSTILE_NAME]
    assert HOSTILE_NAME in check["detail"]
    assert check == hostile_project.scan_report["checks"][0]


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r18_sec_1_every_endpoint_gets_it_from_one_seam(auth_client,
                                                              hostile_project):
    """The seam, not the field. `DEFAULT_RENDERER_CLASSES` is one line of settings and
    covers every endpoint this API has or will have — including the error bodies the
    audited exception handler returns, which are also composed from stored text.

    Asserted across the endpoints that can carry a report today plus one that cannot, so
    the pin says "the renderer is in the path" rather than "this view was remembered".
    """
    from rest_framework.settings import api_settings

    from hub.renderers import ContainedJSONRenderer

    assert api_settings.DEFAULT_RENDERER_CLASSES == [ContainedJSONRenderer]

    for path in (f"/api/v1/projects/{hostile_project.pk}/readiness/",
                 "/api/v1/projects/",
                 "/api/v1/projects/999999/readiness/"):
        response = auth_client.get(path)
        assert not presentation._TEXT_CONTROL_RE.search(
            response.content.decode("utf-8")), path


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r18_sec_1_an_ordinary_response_is_untouched(auth_client, hostile_project):
    """The over-correction guard this fleet has needed at every layer: a legible path
    stays legible. `UNICODE_JSON` is why a Chinese filename is readable in an API
    response, and an escaper reaching beyond the class would undo the only reason it is
    on."""
    hostile_project.scan_report["checks"][0]["refused_paths"] = ["報表/結算.ts"]
    hostile_project.scan_report["checks"][0]["detail"] = "1 file: 報表/結算.ts"
    hostile_project.save()

    response = auth_client.get(f"/api/v1/projects/{hostile_project.pk}/readiness/")

    assert "報表/結算.ts".encode() in response.content
    assert b"\\u5831" not in response.content


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r18_arch_1_the_authority_is_the_one_in_presentation(auth_client,
                                                                   hostile_project):
    """R18-ARCH-1: one authority, every exit.

    The renderer applies `presentation.json_safe` — the same function `--json` uses,
    over the same `CONTROL_CLASS` the text renderer escapes for display. Patching it is
    how a test asserts there is one of it, rather than a fourth copy of a range list that
    agrees today.
    """
    from hub import renderers

    original = renderers.presentation.json_safe
    try:
        renderers.presentation.json_safe = lambda text: '{"sentinel": true}'
        response = auth_client.get(f"/api/v1/projects/{hostile_project.pk}/readiness/")
    finally:
        renderers.presentation.json_safe = original

    assert json.loads(response.content) == {"sentinel": True}


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r18_sec_1_the_sim_fixtures_capture_data_not_rendered_bytes():
    """Why no §F8 payload moved, asserted rather than observed.

    `scripts_dev/sim_fixture_payloads.py` captures `Serializer(...).data` through
    `json.loads(json.dumps(...))` — the PARSED object, which is what the browser has
    after `JSON.parse`. The renderer changes the spelling of bytes on the wire and
    nothing else, so a capture taken before it and one taken after are identical, and the
    drift gate comparing sim.js against a fresh run is unaffected by construction rather
    than by luck.

    Demonstrated on the two representations of one payload: escaping the rendered string
    changes the bytes, and parsing gives the same object back.
    """
    payload = {"detail": "1 file:\n" + HOSTILE_NAME, "refused_paths": [HOSTILE_NAME]}

    rendered = json.dumps(payload, ensure_ascii=False)
    escaped = presentation.json_safe(rendered)

    assert escaped != rendered, "the fixture premise would be vacuous"
    assert json.loads(escaped) == payload == json.loads(rendered)


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
@pytest.mark.parametrize("media_type,context", [
    ("application/json; indent=2", {}),          # asked for through the media type
    ("application/json", {"indent": 2}),         # …and through the renderer context
])
def test_issue_r18_sec_1_an_indented_response_stays_indented_and_valid(media_type,
                                                                       context):
    """The renderer passes BOTH of DRF's indent channels through, and escaping does not
    disturb the structure they produce.

    Found by `make mutation`: three mutants replaced `accepted_media_type` and
    `renderer_context` with `None` and survived, because nothing asked this renderer for
    indented output. DRF reads the indent from the media type's parameter OR the context,
    so dropping either silently turns pretty-printing off — and pretty-printing is the one
    mode where the document contains real newlines outside a string, which is exactly the
    case `json_safe` excludes newline from the class for. The two questions are the same
    question, so one test answers both.
    """
    from hub.renderers import ContainedJSONRenderer

    payload = {"detail": "1 file:\n" + HOSTILE_NAME, "refused_paths": [HOSTILE_NAME]}

    rendered = ContainedJSONRenderer().render(payload, media_type, context).decode()

    assert "\n" in rendered, "the indent was dropped on the way to super().render()"
    assert json.loads(rendered) == payload, "escaping broke the document's structure"
    assert not presentation._TEXT_CONTROL_RE.search(rendered)
