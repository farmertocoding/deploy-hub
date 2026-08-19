// dom-bidi-display (round 20): the DOM exit of the presentation authority.
//
// The API escapes repo-controlled text data-preservingly, so `JSON.parse` recovers the
// real code point and React renders it in a text node — reordering or hiding the display
// of a filename the operator is deciding whether to trust. `safePath`/`safeText` make the
// bidi/zero-width/control class visible, in the exact spelling the CLI and JSON exits use,
// driven by the class GENERATED from `scanner/presentation.py`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { safePath, safeText } from "../src/safe-display.js";

const RLO = "‮";        // right-to-left override
const ISO_OPEN = "⁦";   // left-to-right isolate
const ISO_CLOSE = "⁩";  // pop directional isolate
const ZWSP = "​";       // zero-width space
const BOM = "﻿";
const ESC = "";

// A surrogate code unit with no partner — what tearing an astral pair leaves behind, and
// what a browser paints as U+FFFD. Not `[\uD800-\uDFFF]`: the two halves of a WELL-FORMED
// pair are in that range too, and they are exactly what has to survive.
const LONE_SURROGATE =
  /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

test("a bidi-spoofed filename is made visible, not left to reorder", () => {
  // The classic Trojan-Source display: `invoice⁦gpj.exe⁩.ts` reads `invoice.exe...`.
  const name = `invoice${ISO_OPEN}gpj.exe${ISO_CLOSE}${ZWSP}.ts`;
  const rendered = safePath(name);

  // No raw format/control code point survives to the text node.
  for (const cp of [ISO_OPEN, ISO_CLOSE, ZWSP, RLO, BOM])
    assert.ok(!rendered.includes(cp), `raw ${cp.codePointAt(0)!.toString(16)} survived`);
  // …and it is NAMED, so the operator can still identify the file.
  assert.equal(rendered, "invoice\\u2066gpj.exe\\u2069\\u200b.ts");
});

test("legit CJK and RTL-script letters are untouched", () => {
  // The class is the FORMAT/control set, not scripts — an Arabic, Hebrew or Chinese
  // filename must render as its letters, or the fix is worse than the bug (round-6b).
  assert.equal(safePath("تقرير.ts"), "تقرير.ts");        // Arabic letters
  assert.equal(safePath("報表·結算.ts"), "報表·結算.ts");   // CJK
  assert.equal(safeText("דו”.md"), "דו”.md");    // Hebrew + a curly quote
});

test("safePath mirrors Python safe_path byte for byte, named escapes included", () => {
  // The parity that makes 'one name, one rendering, across every exit' true rather than
  // asserted: these are the exact strings `scanner.presentation.safe_path` produces.
  assert.equal(safePath(`a\\b${RLO}c`), "a\\\\b\\u202ec");   // backslash doubled (F16-1)
  assert.equal(safePath(ESC), "\\x1b");                       // <0x100 -> \xNN
  assert.equal(safePath("\udc9b"), "\\udc9b");                // lone surrogate named
  // F20-BIDI-1: the three points where `repr` uses a NAMED escape — the DOM emitted
  // `\x09`/`\x0a`/`\x0d` here and every other exit emits these, so a refused path with a
  // literal newline read two ways. `safe_path` escapes the newline (full class).
  assert.equal(safePath("two\tlines\nand\rmore.ts"), "two\\tlines\\nand\\rmore.ts");
  // …and NOT the near-neighbours `repr` does not name: \v and \f stay \x0b/\x0c.
  assert.equal(safePath("a\vb\fc"), "a\\x0bb\\x0cc");
  // R21-SEC-1: THE SURROGATE BOUNDARY, which is where the two implementations could
  // diverge and where the "every point" claim above was not yet true. Python matches by
  // CODE POINT; this module matched by code unit until the `u` flag, so an astral pair
  // whose trail surrogate fell in U+DC80-DCFF was torn in half here and passed through
  // intact there. The right-hand sides are the exact `scanner.presentation.safe_path`
  // output for each input.
  assert.equal(safePath("\udc7f"), "\udc7f");                 // below the range: kept
  assert.equal(safePath("\udc80"), "\\udc80");                // first of the range
  assert.equal(safePath("\udcff"), "\\udcff");                // last of the range
  assert.equal(safePath("a\u{1F480}b\udc9bc"), "a\u{1F480}b\\udc9bc");
});

test("safeText keeps the server's newlines and does NOT double backslashes", () => {
  // `safe_text` is applied more than once by design in the CLI, so it is idempotent —
  // it does not double the backslash the way `safe_path` does, and it keeps `\n` because
  // a readiness detail's line breaks are the scanner's structure.
  assert.equal(safeText(`line one\nline two${RLO}`), "line one\nline two\\u202e");
  assert.equal(safeText("a\\b"), "a\\b");                     // NOT doubled
  assert.equal(safeText(safeText(`x${RLO}`)), safeText(`x${RLO}`)); // idempotent
  // F20-BIDI-1 for the text variant: tab and CR ARE escaped (named), only U+000A is kept.
  assert.equal(safeText("a\tb\nc\rd"), "a\\tb\nc\\rd");
  // R21-SEC-1: the same surrogate boundary, on the prose sanitizer.
  assert.equal(safeText("\udc7f"), "\udc7f");
  assert.equal(safeText("\udc80"), "\\udc80");
  assert.equal(safeText("\udcff"), "\\udcff");
  assert.equal(safeText("a\u{1F480}b\udc9bc"), "a\u{1F480}b\\udc9bc");
});

test("R21-SEC-1: an astral character is not torn in half by the surrogate range", () => {
  // The class carries U+DC80-DCFF because a `surrogateescape` byte is not a character
  // (R15-SEC-2). Matched by CODE UNIT — a regex without the `u` flag — that range also
  // hits the TRAIL surrogate of a well-formed pair, which is every astral code point
  // whose low ten bits are 0x080-0x0FF: U+1F480 💀 and its neighbours, CJK Ext-B, about
  // an eighth of the astral planes. `scanner.presentation.safe_path` passes all of them
  // through untouched, so this was the DOM spelling a name the other four exits do not.
  assert.equal(safePath("\u{1F480}-report.ts"), "\u{1F480}-report.ts");
  assert.equal(safeText("\u{1F480}-report.ts"), "\u{1F480}-report.ts");
  assert.equal(safePath("\u{20080}-report.ts"), "\u{20080}-report.ts");   // CJK Ext-B

  // …and the output is WELL-FORMED. The torn spelling left a bare high surrogate in the
  // text node, which a browser paints as U+FFFD — so `x💀.ts` and `x𠂀.ts` (two different
  // files) rendered as the same glyphs, the two-names-one-display defect the zero-width
  // members of this class exist to prevent.
  for (const name of ["x\u{1F480}.ts", "x\u{20080}.ts"]) {
    const rendered = safePath(name);
    assert.equal(rendered, name);
    assert.ok(!LONE_SURROGATE.test(rendered),
      `a lone surrogate reached the DOM from ${JSON.stringify(name)}`);
  }
  assert.notEqual(safePath("x\u{1F480}.ts"), safePath("x\u{20080}.ts"));
});

test("null/undefined pass through (a React child may be either)", () => {
  assert.equal(safePath(undefined), undefined);
  assert.equal(safeText(null), null);
});
