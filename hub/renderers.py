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
"""
from rest_framework.renderers import JSONRenderer

from scanner import presentation


class ContainedJSONRenderer(JSONRenderer):
    """`rest_framework.renderers.JSONRenderer`, with the class escaped on the way out."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        rendered = super().render(data, accepted_media_type, renderer_context)
        if not rendered:
            # DRF renders `None` as `b""` for a 204; there is nothing to escape and
            # `b"".decode()` would be a pointless round trip on every empty response.
            return rendered
        # `json_safe` works on the DUMPED STRING for the reason its docstring gives:
        # `json.dumps` has already escaped every newline inside a string, so the only raw
        # ones left are a pretty-printer's structure. DRF renders compact unless an
        # `indent` is asked for — through the media type or the renderer context, both of
        # which are passed through above — and this is correct either way, which the
        # indent test pins.
        #
        # `decode()`/`encode()` without a codec name: both default to UTF-8 by definition
        # rather than by locale, and it is the same call DRF's own renderer makes on the
        # way out. Naming the codec here would be a second spelling of that agreement —
        # and, as the mutation gate pointed out, an unfalsifiable one: codec lookup is
        # case-insensitive, so `"utf-8"` and `"UTF-8"` are the same argument and no test
        # can tell them apart.
        return presentation.json_safe(rendered.decode()).encode()
