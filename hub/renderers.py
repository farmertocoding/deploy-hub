"""The API's exit, held to the same rule as the CLI's two (R18-SEC-1 / R18-ARCH-1).

`scanner/presentation.py` states the boundary: repo-controlled text is escaped where it
reaches a device that interprets it, and the class it is escaped against is one constant.
Rounds 15-17 applied that at `render_text`'s seam and at `--json`'s. The HTTP API was the
third exit and had nothing: DRF renders with `ensure_ascii=False` (`UNICODE_JSON` defaults
to True and no setting overrode it), so a stored check detail went out as itself —
U+009B, the bidi overrides, the zero-width family, the BOM, in the response bytes.

A JSON API's consumers are terminals at least as often as they are parsers — `curl`,
`http`, `jq`, a CI job's log — which is the same argument that made `--json` a finding.

AT THE RENDERER, WHICH IS A SEAM, and that is the whole design decision here. The
alternative was serializer-level field transforms, and it is the shape every finding in
this series has been: a per-field opt-in that the next field forgets. `DEFAULT_RENDERER_
CLASSES` is one line of settings, it covers every endpoint this API has or will have, and
it covers the error bodies the audited exception handler returns as well — which are
composed from stored text too.

WHAT IT IS NOT: a repair. `\\uXXXX` is a spelling, so `JSON.parse` and `json.loads` return
the identical code points, the React UI renders exactly what it rendered before, and a
client that stores the report keeps the true bytes. A renderer that changed the DATA would
be the scanner lying about what it found, one layer further out.

── R19-SEC-1: WHY THIS DOES NOT CALL super().render() ──────────────────────────

The first cut did, and it was a repo-controlled persistent denial of service. DRF's
`JSONRenderer.render` `.encode()`s the string it built BEFORE returning it, and a lone
surrogate — the U+DC80-DCFF `surrogateescape` gives a bare undecodable byte (R15-SEC-2) —
cannot be UTF-8 encoded. So `super().render()` RAISED, before `json_safe` (the one thing
that would have spelled the surrogate `\\udc9b`) ever ran. `json_safe`'s surrogate
handling was dead on this path.

Two ways to reach it, both real:

  * OPERATOR INPUT — a `"\\udc9b"` escape in a POST body echoed into a DRF ChoiceField
    error message renders a 400 that raises, so the audited exception handler composes its
    response and then the renderer 500s on the way out;
  * REPO-CONTROLLED AND PERSISTENT — a committed symlink named with a bare 0x9b byte is
    stored through `surrogateescape` into `scan_report.refused_paths`, so `GET
    …/readiness/` raises every time. That project's primary screen is a permanent 500,
    with no interaction at all — a repository can take its own readiness report offline.

So this produces the STRING, escapes it, and encodes LAST — the order `--json` already
uses (`json_safe(json.dumps(...)).encode()`). The DRF render body is replicated rather
than called: its indent (from the media-type parameter and the renderer context both), its
`ensure_ascii=False` for CJK, its compact separators, its U+2028/U+2029 escape (which
`json_safe` also covers, since both are in `CONTROL_CLASS`). `encode()` cannot raise now,
because `json_safe` has removed every code point that is not a Unicode scalar value first.
"""
from rest_framework.renderers import (
    LONG_SEPARATORS,
    SHORT_SEPARATORS,
    JSONRenderer,
)
from rest_framework.utils import json

from scanner import presentation


class ContainedJSONRenderer(JSONRenderer):
    """`rest_framework.renderers.JSONRenderer`, with the class escaped BEFORE the encode.

    The class body carries DRF's `ensure_ascii`, `compact`, `strict` and `encoder_class`
    so its own settings still decide those; only the final two steps — escape, then encode
    — are this subclass's, and they are in that order for R19-SEC-1's reason.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""

        renderer_context = renderer_context or {}
        indent = self.get_indent(accepted_media_type, renderer_context)

        if indent is None:
            separators = SHORT_SEPARATORS if self.compact else LONG_SEPARATORS
        else:
            # `None` lets `json.dumps` pick its indent-mode default, which is
            # byte-for-byte DRF's `INDENT_SEPARATORS` `(',', ': ')` — so this is the same
            # output with nothing redundant to spell (or to mutate against no effect).
            separators = None

        # The string, not the bytes — this is the whole of the R19-SEC-1 fix.
        #
        #   * `cls=self.encoder_class` is DRF's, which renders the datetimes/Decimals a
        #     Response may carry that plain `json` cannot;
        #   * `ensure_ascii=self.ensure_ascii` is DRF's `UNICODE_JSON` — False here, which
        #     keeps a Chinese path legible and leaves the rest of CONTROL_CLASS for
        #     `json_safe`.
        #
        # `allow_nan` is NOT passed, deliberately: DRF's `encoder_class` refuses a bare
        # `NaN`/`Infinity` on its own (a non-finite float raises `ValueError` here whatever
        # `allow_nan` says), so restating it would be a redundant argument that reads as
        # load-bearing. The refusal is a property of the encoder, and it is pinned by
        # `test_issue_r19_sec_1_a_non_finite_number_is_refused_not_emitted` rather than by
        # an argument of ours.
        rendered = json.dumps(
            data, cls=self.encoder_class,
            indent=indent, ensure_ascii=self.ensure_ascii,
            separators=separators,
        )

        # One authority, and it subsumes DRF's own U+2028/U+2029 escape: both are in
        # CONTROL_CLASS, so `json_safe` spells them `\\u2028`/`\\u2029` along with
        # U+009B, the bidi family, the zero-width family, the BOM and every lone
        # surrogate. AFTER this, `encode()` cannot raise — nothing left is a
        # non-encodable code point.
        return presentation.json_safe(rendered).encode()
