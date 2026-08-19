// The DOM exit of the presentation authority (dom-bidi-display, round 20).
//
// The API's `json_safe` escaping is DATA-PRESERVING: `\uXXXX` on the wire, and
// `JSON.parse` recovers the real code point. That is correct for a transport, and it
// means a repo-controlled filename carrying a bidi override (U+202E, the isolates
// U+2066-2069, LRM/RLM) or a zero-width code point (U+200B-200D, U+2060, U+FEFF) arrives
// in the browser AS ITSELF, and React renders it in a text node — so the browser
// REORDERS or HIDES the display of a name the operator is deciding whether to trust.
// `invoice‮gpj.exe` reads `invoiceexe.jpg`; two names differing only by a U+200B
// look identical. Display-only, no execution — but the whole point of the readiness
// screen is that the operator sees the truth about a repository.
//
// WHY ESCAPE AND NOT ISOLATE. `unicode-bidi: isolate` + `dir=auto` stops a string from
// reordering the UI text AROUND it; it does NOT neutralise an explicit RLO/isolate INSIDE
// the string, which still reorders that string's own glyphs (CVE-2021-42574, the
// Trojan-Source paper: rendering must make the controls visible or reject them, not
// merely isolate the container). Stripping them would name a file that does not exist.
// So the code points are made VISIBLE, in the exact `\xNN`/`\uNNNN` spelling the CLI's
// refusal list and the JSON exits use — one name, one rendering, across all five exits.
//
// THE CLASS IS GENERATED, not hand-written: `CONTROL_CLASS` / `TEXT_CONTROL_CLASS` come
// from `frontend/src/api/presentation.js`, which `make generate-client` writes from
// `scanner/presentation.py`. This function is the small JS-native transform over that
// class — the counterpart of `presentation.safe_path` in Python — so there is no second
// copy of the range list, which was the round-15 concern about a JS security transform.
//
// Ordinary CJK and RTL-SCRIPT LETTERS are NOT in the class (it is the format/control set,
// not scripts), so an Arabic or Hebrew or Chinese filename renders as its letters.
import { CONTROL_CLASS, TEXT_CONTROL_CLASS } from "./api/presentation.js";

// THE `u` FLAG IS LOAD-BEARING (R21-SEC-1), and the comment that stood here said the
// opposite for two reasons, both false.
//
// Without `u` the pattern matches by CODE UNIT, so the class's lone-surrogate range
// U+DC80-DCFF — a byte that is not a character, R15-SEC-2 — also matched the TRAIL
// surrogate INSIDE a well-formed astral pair. That is every astral code point whose low
// ten bits are 0x080-0x0FF: U+1F480 💀 and its neighbours, CJK Ext-B, about an eighth of
// the astral planes. The pair came apart — a bare high surrogate emitted into the text
// node (a browser paints it U+FFFD) followed by a spurious `\udcNN` — while Python's
// `safe_path` passed the same name through untouched, so the DOM spelled a name the
// other four exits do not. And the two halves collided: `x💀.ts` and `x𠂀.ts` rendered
// identically, which is the two-names-one-display defect the zero-width members of this
// class are here for.
//
// With `u` the pattern and the subject are both read as CODE POINTS: a well-formed pair
// is ONE code point, and no range in the class contains it. The range still matches an
// actually-lone surrogate, because a `surrogateescape` byte has no partner and so is its
// own code point — and `u` does not reject one in the pattern either: `\udc80` is a
// HexTrailSurrogate, a legal RegExpUnicodeEscapeSequence in Unicode mode.
const CONTROL_RE = new RegExp(`[${CONTROL_CLASS}]`, "gu");
const TEXT_CONTROL_RE = new RegExp(`[${TEXT_CONTROL_CLASS}]`, "gu");

// Mirror of `presentation._escaped`, which is `repr(char)[1:-1]` in Python — and that is
// what the other four exits emit, so the DOM must match it exactly or one name has two
// spellings (F20-BIDI-1). `repr` uses NAMED escapes for tab/newline/CR before falling
// back to `\xNN` (< U+0100) / `\uNNNN` (>=). It does NOT name \v (U+000B) or \f (U+000C) —
// those are `\x0b`/`\x0c` — so the named set is exactly these three. Only they can render
// in a text node at all (the rest are invisible or reordering controls), which is why the
// divergence was benign-but-real: a refused path with a literal newline read `…\x0a…` in
// the DOM and `…\n…` everywhere else.
const NAMED = { 0x09: "\\t", 0x0a: "\\n", 0x0d: "\\r" };

function escapeMatch(ch) {
  const cp = ch.codePointAt(0);
  if (cp in NAMED) return NAMED[cp];
  return cp < 0x100
    ? "\\x" + cp.toString(16).padStart(2, "0")
    : "\\u" + cp.toString(16).padStart(4, "0");
}

// `safePath`/`safeText` mirror the Python pair EXACTLY, asymmetry included:
//
//   * `safePath` doubles the literal backslash FIRST, so the encoding is injective — one
//     rendered string names one file (F16-1). It is for the `refused_paths` list and for
//     single-line labels like a check title.
//   * `safeText` does NOT double, because Python's `safe_text` does not: it is applied
//     more than once by design (per field AND at the CLI's render seam), so it has to be
//     idempotent, and doubling is not. It keeps `\n`, because a readiness detail's line
//     breaks are the scanner's own structure, rendered with `white-space: pre-line`.
//
// The two are kept byte-identical to the Python functions by
// `tests/safe-display.test.ts`, which pins the exact spelling on a hostile name — so
// "one name, one rendering, across every exit" is checked, not asserted.
export function safePath(value) {
  if (value == null) return value;
  return String(value).replace(/\\/g, "\\\\").replace(CONTROL_RE, escapeMatch);
}

export function safeText(value) {
  if (value == null) return value;
  return String(value).replace(TEXT_CONTROL_RE, escapeMatch);
}
