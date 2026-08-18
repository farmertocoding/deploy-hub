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
});

test("null/undefined pass through (a React child may be either)", () => {
  assert.equal(safePath(undefined), undefined);
  assert.equal(safeText(null), null);
});
