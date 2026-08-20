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


# ── R19-SEC-1: the surrogate that 500'd before json_safe could run ───────────

SURROGATE_NAME = "csi\udc9bmark.ts"   # os.listdir(surrogateescape) of a bare 0x9b byte


def _render(data, media_type=None, context=None):
    """One check's Response body, through the configured renderer.

    `api_settings.DEFAULT_RENDERER_CLASSES[0]` rather than `ContainedJSONRenderer`
    imported directly, so the test breaks if the settings registration is removed — the
    finding is about what the API actually uses, not about a class that exists.
    """
    from rest_framework.settings import api_settings

    renderer = api_settings.DEFAULT_RENDERER_CLASSES[0]()
    return renderer.render(data, media_type, context or {})


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_a_surrogate_does_not_raise_at_the_renderer():
    """R19-SEC-1 (medium). `super().render()` `.encode()`s BEFORE `json_safe` runs, and a
    lone surrogate cannot be UTF-8 encoded, so the renderer raised on the one class its
    own escaper was written for. Measured before the fix:

        RAISED: UnicodeEncodeError: 'utf-8' codec can't encode character '\\udc9b'

    An exception at the renderer is a 500 after the view has already decided the response
    — for a 400 error body, after the audited exception handler has already run.
    """
    body = _render({"refused_paths": [SURROGATE_NAME], "detail": f"1 file:\n{SURROGATE_NAME}"})

    assert b"\\udc9b" in body, "the surrogate is named nowhere"
    assert json.loads(body.decode("utf-8")) == {
        "refused_paths": [SURROGATE_NAME], "detail": f"1 file:\n{SURROGATE_NAME}"}, (
        "the parser does not get the true code point back")


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_reach_a_a_choicefield_error_stays_a_400_with_an_escaped_body():
    """REACH PATH (a): operator input echoed into a DRF error.

    A `ChoiceField` renders `'"{input}" is not a valid choice.'` — the input VERBATIM,
    unlike the wizard's own validation which uses `repr` and so was already safe. JSON
    input carries a lone surrogate fine (`json.loads('"\\udc9b"')` is U+DC9B), so a POSTed
    choice reaches the error body raw, and rendering it 500'd.

    Driven through the real renderer on a real ChoiceField error rather than a
    hand-built body, because the claim is that DRF composes this shape and the renderer
    survives it — the product has no ChoiceField, so the field is the test's, the
    renderer and the error machinery are DRF's.
    """
    from rest_framework import serializers

    class _ChoiceSerializer(serializers.Serializer):
        exposure = serializers.ChoiceField(choices=["public", "mesh_only"])

    serializer = _ChoiceSerializer(data={"exposure": SURROGATE_NAME})
    assert not serializer.is_valid()

    # The 400 body DRF hands the renderer: `{"exposure": ['"csi\udc9bmark.ts" is not a
    # valid choice.']}`, the surrogate verbatim.
    detail = serializer.errors
    assert SURROGATE_NAME in str(detail["exposure"][0]), "DRF stopped echoing the input"

    body = _render(detail)

    assert b"\\udc9b" in body
    parsed = json.loads(body.decode("utf-8"))
    assert SURROGATE_NAME in parsed["exposure"][0]


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_reach_b_a_committed_bare_byte_keeps_readiness_online(
        auth_client, tmp_path):
    """REACH PATH (b), the escalation: a committed file makes readiness a PERMANENT 500.

    The whole route, real scanner included: a symlink named with a bare 0x9b byte —
    invalid UTF-8, legal on the filesystem — is stored by `os.listdir`'s
    `surrogateescape` into `scan_report.refused_paths`, and `GET …/readiness/` renders
    that report on every request. Before the fix the render raised, so the project's
    primary screen was down for as long as the file was committed, with zero interaction.

    Built through `os.fsencode` because the point is that the name is BYTES, not text.
    """
    import os

    from scanner import core as scanner_core

    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    (neighbour / "target.ts").write_text("export const x = 1;\n", encoding="utf-8")
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    link = os.path.join(os.fsencode(str(root / "src")), b"csi\x9bmark.ts")
    try:
        os.symlink(os.path.relpath(os.fsencode(str(neighbour / "target.ts")),
                                   os.fsencode(str(root / "src"))), link)
    except OSError as exc:
        pytest.skip(f"this filesystem refuses a 0x9b filename: {exc}")

    report = scanner_core.scan(str(root))
    refused = [p for c in report["checks"] for p in (c.get("refused_paths") or [])]
    assert any("\udc9b" in p for p in refused), (
        "the scanner did not store the bare byte — the fixture is not exercising path b")

    project = Project.objects.create(
        name="bare-byte", slug="bare-byte", git_url="https://github.com/o/r.git",
        scan_report=report, scanned_at="2026-08-18T00:00:00Z")

    response = auth_client.get(f"/api/v1/projects/{project.pk}/readiness/")

    assert response.status_code == 200, "readiness is a 500 — the report cannot be read"
    assert b"\\udc9b" in response.content
    parsed = json.loads(response.content.decode("utf-8"))
    parsed_refused = [p for c in parsed["warnings"] for p in (c.get("refused_paths") or [])]
    assert any("\udc9b" in p for p in parsed_refused), (
        "the parsed report lost the byte the scanner found")


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_every_class_member_round_trips_through_the_renderer():
    """The R13-REM-1 gap this closes: the 230 lines of renderer/escaper tests had ZERO
    surrogate coverage, which is how the encode-before-escape order survived.

    Every member of `CONTROL_CLASS` — the surrogate range INCLUDED — through the renderer
    and back: escaped on the wire, identical after a parse. The scanner still reports the
    true bytes; only their spelling changes.
    """
    every = "".join(map(chr, range(0x110000)))
    members = [c for c in every if presentation._CONTROL_RE.match(c)]
    assert any(0xDC80 <= ord(c) <= 0xDCFF for c in members), "the surrogate range is gone"

    for char in members:
        payload = {"p": f"x{char}y"}
        body = _render(payload)
        text = body.decode("utf-8")
        assert char not in text, f"U+{ord(char):04X} reached the wire raw"
        assert json.loads(text) == payload, f"U+{ord(char):04X} did not round-trip"


# ── R19-SEC-1: the replicated DRF render body, pinned line by line ───────────
#
# The renderer no longer calls `super().render()` (which encodes before json_safe can
# run), so DRF's dump contract is this subclass's now — and `make mutation` mutated every
# argument of it. These pin the ones that carry meaning; each names the mutant it kills.

@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_none_data_renders_empty_bytes():
    """A 204/None response is `b""` — DRF's contract, and the `if data is None` short
    circuit `json_safe` must not be asked to escape."""
    assert _render(None) == b""


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_compact_output_uses_drfs_short_separators():
    """No spaces after `,` or `:` — DRF renders compact, and a consumer diffing API
    output against a fixture depends on the exact bytes. Kills the separator mutants
    (dropped, `None`, or the compact/indent branch flipped)."""
    assert _render({"a": 1, "b": 2}) == b'{"a":1,"b":2}'


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_an_indented_response_is_valid_and_escaped():
    """The indent branch: still valid JSON, still escaped, structure intact. Kills the
    branch-condition and indent-separator mutants."""
    body = _render({"detail": SURROGATE_NAME}, "application/json; indent=2", {})

    assert b"\n" in body, "indent was dropped"
    assert json.loads(body.decode("utf-8")) == {"detail": SURROGATE_NAME}
    assert b"\\udc9b" in body


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_the_drf_encoder_renders_types_plain_json_cannot():
    """`cls=self.encoder_class` — a Response may carry a `Decimal` or a `datetime`, which
    DRF's encoder serializes and the stdlib encoder raises on. Kills the `cls=None` and
    dropped-`cls` mutants."""
    import datetime as dt
    from decimal import Decimal

    body = _render({"when": dt.datetime(2026, 8, 18, 12, 0), "amount": Decimal("1.5")})
    parsed = json.loads(body.decode("utf-8"))

    assert parsed["when"].startswith("2026-08-18")
    assert parsed["amount"] == 1.5


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_a_non_finite_number_is_refused_not_emitted():
    """A bare `NaN`/`Infinity` is invalid JSON for most parsers, and this renderer never
    emits one. The refusal is DRF's `encoder_class`'s (it raises `ValueError` on a
    non-finite float regardless of `allow_nan`), which is why the renderer does not
    restate `allow_nan` — this pins that behaviour rather than an argument of ours."""
    import pytest as _pytest

    with _pytest.raises(ValueError):
        _render({"x": float("nan")})


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r19_sec_1_cjk_stays_legible_and_the_class_is_still_escaped():
    """`ensure_ascii=self.ensure_ascii` is DRF's `UNICODE_JSON` (False here), which is why
    a Chinese path is readable in the response — the whole reason this renderer replicates
    DRF's body instead of forcing `ensure_ascii=True`. The class is escaped regardless,
    because `json_safe` does not read this setting.

    A PROPERTY PIN, not a mutant kill: `self.ensure_ascii` is a DRF class attribute frozen
    at import to False, so `ensure_ascii=None` renders identically and no runtime setting
    change can separate them — that mutant is recorded equivalent in WAIVERS.md.
    """
    body = _render({"p": "報表", "bad": SURROGATE_NAME})

    assert "報表".encode() in body, "CJK was escaped — the renderer lost its whole point"
    assert b"\\udc9b" in body, "…but the class is still escaped"
    assert json.loads(body.decode("utf-8")) == {"p": "報表", "bad": SURROGATE_NAME}
