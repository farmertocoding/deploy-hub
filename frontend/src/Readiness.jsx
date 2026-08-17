// F7-lite (Phase 1): project list → three-tier readiness report → wizard → materialize.
// Same plain-React idiom as App.jsx — shadcn/Tailwind (§A8) still deferred; mockup
// first per the working agreement, styling later on request.
//
// §F9 rules applied here: status is never color-only (every tier carries a symbol +
// word); dark palette matches Phase 0; every data panel carries its staleness stamp.
// §F8: the states (empty / loading + loading-report + loading-wizard / live / stale /
// error / degraded) are reachable without a backend via ?sim=<state> — see sim.js, and
// the contract test that pins the fixtures to the generated zod schemas. TWO states
// reach the 409 panel with the button ENABLED, and they are different refusals: `stale`
// is a report that moved between the GET and the POST, and `live` on atlas-edge is the
// warnings gate, which the ack checkbox below actually clears. (`accepted` left with
// D-012: no answer clears a blocker this phase.)
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

// R11-UX-F5: a control that cannot be pressed has to LOOK like one.
//
// The browser's own `:disabled` styling is the reason nobody usually thinks about this,
// and an inline `style=` is exactly what overrides it: `background` and `color` set here
// win over the user-agent stylesheet, so the disabled Materialize button and the disabled
// Save button rendered PIXEL-IDENTICAL to their enabled selves. Every refusal on this
// screen was therefore announced by a button that looked pressable — the operator clicks
// it, nothing happens, and nothing on screen explains the difference between "nothing
// happened" and "it did not take my click".
//
// Inline, because this tree has no stylesheet at all (§A8: shadcn/Tailwind arrive with
// the first real screen) and inventing one for a hover state would be the larger change.
// Three signals rather than one, per §F9's never-color-only rule: dimmer text, a flatter
// background, and `not-allowed` under the pointer.
const disabledBox = (disabled) => disabled
  ? { ...box, color: "#6e7681", background: "#15181e", borderColor: "#2a2e35",
      cursor: "not-allowed" }
  : box;
// R9-8: the plural is per tier, not `word + "s"`.
//
// Two of the four tiers do not take an -s and the naive rule produced both of them:
// "3 Deferred to sandboxs" (the plural is of the CHECKS, and there is one sandbox), and
// "2 Advices" (advice is a mass noun in English — you have two pieces of it). The
// singular is the one a reader would write; where they are the same, they are the same on
// purpose and saying so here is cheaper than the next reader re-deriving it.
const TIER_BADGE = {
  blocker: { sym: "⛔", one: "Blocker", many: "Blockers", color: "#ff7b72" },
  warning: { sym: "⚠", one: "Warning", many: "Warnings", color: "#e3b341" },
  advice: { sym: "ℹ", one: "Advice", many: "Advice", color: "#79c0ff" },
  pending_sandbox: { sym: "⏳", one: "Deferred to sandbox",
                     many: "Deferred to sandbox", color: "#8b949e" },
  // R12-F12-2: `ok` has no SECTION — the payload groups the four tiers the screens
  // render and `ok` appears in `summary` as a count and nowhere else — but it now has a
  // word, because the scope line below counts it. Here rather than in that component, so
  // there is still exactly one place this screen decides what a tier is called and how it
  // pluralizes (R9-8: the plural is per tier, not `word + "s"`).
  ok: { sym: "✓", one: "OK", many: "OK", color: "#3fb950" },
};

export function Badge({ tier, n }) {
  const b = TIER_BADGE[tier];
  // Symbol + word + count: readable colorblind, greyscale, or by screen reader.
  //
  // R10-UX-F7 — NO aria-label, and the reason is the finding R9-8 half-fixed. That label
  // used to be `${n} ${word}` — the singular at every count — so a screen reader heard
  // "3 Blocker" while the screen read "3 Blockers". R9-8 derived the label from the
  // visible text so the two could not disagree, which is right and does not go far
  // enough: on a plain <span> whose text already reads "⛔ 3 Blockers", an aria-label is
  // not a clarification, it is a SECOND rendering that REPLACES the first for the reader
  // that uses it. Two spellings of one fact is the arrangement §F9 exists to forbid, and
  // the fix for two spellings is one spelling.
  //
  // What is lost is the glyph's name, and it was never in the label anyway — the label
  // began at the count. The word beside it ("Blockers") is the accessible name of the
  // tier, in the text, for everyone.
  const text = `${n} ${n === 1 ? b.one : b.many}`;
  return (
    <span style={{ color: b.color, marginRight: 10 }}>
      {b.sym} {text}
    </span>
  );
}

// R12-F12-2: what this report is a report OF.
//
// The panel rendered the findings and nothing about the scan that produced them, so two
// facts an operator needs before trusting a green screen were on it nowhere:
//
//   * WHICH MODULES RAN. `modules` is in every payload and was rendered by nothing. A
//     Django repo scanned as a plain static site produces a short, calm, entirely honest
//     report — of the wrong suite. "✓ No findings" and "scanned by: static" are different
//     screens, and only one of them was reachable;
//   * HOW MANY CHECKS PASSED. `summary` carries `ok`, and the sections deliberately do
//     not (the payload groups the four tiers the screens render). So "10 checks, all ok"
//     and "1 check, ok" rendered identically — a green tick over a suite that barely ran
//     looks exactly like a green tick over one that ran fully.
//
// PAYLOAD FIELDS ONLY, which is §4b applied to a line that is not a refusal: `modules`
// and `summary` verbatim, the tier words from `TIER_BADGE` (this screen's existing one
// spelling, R9-8), and no sentence claiming anything the payload does not say. The tiers
// are listed in TIER order rather than in whatever order `summary`'s keys arrive in,
// because the payload's key order is the server's serialization detail and this is a
// reading order.
//
// The `pending_sandbox` word already carries the execution distinction — "Deferred to
// sandbox" is what `execution: "executing"` means on this screen, and it is the same
// table the section heading uses, so the two cannot drift.
const SCOPE_TIERS = ["blocker", "warning", "advice", "pending_sandbox", "ok"];

export function ReportScope({ report }) {
  const r = report || {};
  const modules = r.modules || [];
  const summary = r.summary || {};
  const counted = SCOPE_TIERS.filter((tier) => summary[tier]);
  if (!modules.length && !counted.length) return null;
  return (
    <p style={{ color: "#8b949e", margin: "4px 0 12px" }}>
      {!!modules.length && <span>Scanned by {modules.join(", ")}</span>}
      {!!modules.length && !!counted.length && <span> · </span>}
      {counted.map((tier, i) => (
        <span key={tier}>
          {i > 0 && ", "}
          {summary[tier]} {summary[tier] === 1 ? TIER_BADGE[tier].one : TIER_BADGE[tier].many}
        </span>
      ))}
    </p>
  );
}

// R8-1: the Materialize decision, as a named thing rather than an expression in JSX.
//
// Gated on `state.can_materialize`, which is `not preflight(site)` (wizard/views.py
// ::_state) — the same function the POST itself runs, so client and server refuse for
// identical reasons. It used to be gated on the parent's `report.blockers`, which an
// acceptance never rewrites: the button stayed disabled after the very answer that
// unblocked the deploy, under a tooltip telling the operator to re-scan — the one
// operation pinned to change nothing.
//
// THE TOOLTIP IS THE SERVER'S, ALWAYS (spec §4b). `preflight` already distinguishes the
// two refusals in its own detail — it appends "except where a declaration is awaiting
// acceptance, which you clear by answering its confirm in this wizard, not by changing
// the repo" when a pending acceptance is among the blockers — and the first remedy
// discarded that for a string typed here, which is R8-1's own shape one layer down.
// Nothing in this file authors refusal copy; tests/materialize-gate.test.ts greps for
// it. The label is the client's only word, because it is the one thing the payload does
// not say in two syllables and it is what the eye reads before the tooltip.
//
// `hard` is what no answer can clear: `blockers_present` items with no
// `awaiting_acceptance` list. An item carrying one is waiting on this very wizard.
//
// D-012 out of Phase 1 (2026-08-16) leaves this function EXACTLY as it is, and that is
// the spec's instruction rather than an oversight: it gates on `can_materialize` and
// `blocking`, both of which stay server-truth, and no server this phase emits an
// `awaiting_acceptance` list — so the "Answer required" arm is unreachable until the
// mechanism returns, and reachable again the day it does. The alternative is deleting a
// correct reading of a payload shape and re-deriving it later, which is how a client
// ends up authoring its own idea of a refusal. See tests/materialize-gate.test.ts for
// which of its payloads are live and which are held against that return.
export function materializeGate(state) {
  const blocking = state?.blocking || [];
  if (state?.can_materialize)
    return { disabled: false, label: "Materialize manifest", title: "" };
  const title = blocking.map((p) => p.detail).filter(Boolean).join(" · ");
  const blockerProblems = blocking.filter((p) => p.code === "blockers_present");
  const hard = blockerProblems
    .flatMap((p) => p.items || [])
    .filter((item) => !(item.awaiting_acceptance || []).length);
  if (blockerProblems.length && !hard.length)
    return { disabled: true, label: "Answer required", title };
  // Round-9 item 3. A refusal made ENTIRELY of things the operator types into this form
  // is not a blocked deploy, and the ⛔ glyph — which everywhere else on this screen means
  // a blocker-tier finding in the report — said it was. Every clean project met that
  // label before anyone typed the domain: a repository with nothing wrong with it,
  // announced as blocked. Both codes here refuse for the same reason and clear the same
  // way, in this form, with no re-scan and no change to the tree.
  //
  // Named codes rather than "no blockers_present": `scan_required` also arrives without
  // one and is NOT answerable here, so a fallback arm would mislabel it. A code this
  // list has not met keeps the conservative label, which is the safe direction.
  if (blocking.length && blocking.every((p) => ANSWERABLE_REFUSALS.has(p.code)))
    return { disabled: true, label: "Answers needed", title };
  // R10-UX-F5. The round-9 remedy above reserved ⛔ for "a blocker-tier finding in the
  // report", and then left `scan_required` wearing it — a project nobody has scanned
  // yet has no findings at all, and the panel beside this button says exactly that
  // ("Not scanned yet — this project has no readiness report, which is not the same as
  // having nothing to report"). ⛔ contradicted it in the same breath, and the operator
  // reading "Blocked" has no finding to go and look at.
  //
  // A THIRD LABEL rather than folding it into either of the two above: this refusal
  // clears by scanning, which is neither "answer the form" nor "fix the repo and
  // re-scan". Named code, like the arm above and for the same reason — a code this list
  // has not met keeps ⛔, which is the conservative direction.
  if (blocking.length && blocking.every((p) => NEUTRAL_REFUSALS.has(p.code)))
    return { disabled: true, label: "Scan required", title };
  return { disabled: true, label: "⛔ Blocked", title };
}

const ANSWERABLE_REFUSALS = new Set(["answers_missing", "answers_need_reentry"]);
// Refusals that are neither a finding nor an answer: nothing is wrong with the repo and
// nothing in this form clears them. One code today; the set exists so the next one is a
// one-line reviewable edit rather than a new arm.
const NEUTRAL_REFUSALS = new Set(["scan_required"]);

// R9-4: what the client does with the response, as a named thing rather than three
// branches inside an async handler — the same argument `materializeGate` was extracted
// under, and the same test file looks at both.
//
// THE 409 BRANCH USED TO RE-READ NOTHING. It set a message; `onChanged` fired only on
// 201. So a refusal that exists precisely BECAUSE the server's state is not what this
// screen is showing left the screen showing it: in ?sim=stale, a refusal naming a
// committed Stripe key under a panel reading "✓ No findings", with the button still
// enabled. A 409 here is the server telling the client its copy is stale, and the only
// correct response to that is to go and read the current one.
//
// A 500 or a dead socket re-reads nothing on purpose: the server said nothing about this
// site's state, so there is nothing to converge ON, and a refetch would either loop or
// paper over the error with a spinner.
export function materializeOutcome(status, data) {
  if (status === 201)
    return { msg: { ok: true, text: `Manifest v${data.version} created.` },
             reloadWizard: true, refreshProject: true };
  if (status === 409)
    return { msg: { problems: data.problems || [data] },
             reloadWizard: true, refreshProject: true };
  return { msg: { ok: false, text: data.detail || `HTTP ${status}` },
           reloadWizard: false, refreshProject: false };
}

// R9-1: a check's `detail` and `fix_hint` are MULTI-LINE server text, and HTML does not
// believe in newlines. `core.secret-scan` sends fifteen `file:line` findings joined with
// \n, then a blank line and two paragraphs of hint; rendered into a bare <p> the whole
// thing arrived as one run-on paragraph with the filenames run together — the check whose
// entire job is telling an operator WHICH files to go and look at.
//
// `pre-line` rather than `pre`: it honours the newlines the server put there and still
// wraps long lines to the panel, where `pre` would give a paragraph of prose a horizontal
// scrollbar. The blank line between sections survives it, which is how the fix hint's own
// two paragraphs stay two paragraphs.
const PRE_LINE = { whiteSpace: "pre-line", margin: "6px 0" };

// R12-ARCH-1: the fact the scanner's guard accepts as an announcement, rendered.
//
// `CheckResult.refused_paths` (R12-A1) is the machine-readable list of files a check is
// telling the operator were NOT READ. `scanner.core.scan` lets a module take those files
// out of `core.symlinked-files` on the strength of it — and until this rendered, the
// thing being checked was a value on no screen. The guard's own docstring claimed the
// module had "already told the operator", which was true of the prose the guard used to
// read and not of the field that replaced it.
//
// WHY IT IS NOT A SECOND SPELLING OF THE DETAIL, which is the objection this screen has
// sustained before (R10-UX-F7 removed a duplicate `aria-label` for exactly that reason):
// the two are not the same list. `core.symlinked-files` prints ten paths and counts the
// rest — "… and 3 more" — because a report line is for reading; the field carries every
// one. And `node-ts.symlinked-files` prints its paths through `repr`, so a committed file
// called `metri\cs.ts` appears in the sentence with the backslash escaped and here as
// what it is. Where they do coincide — one refused file, named once in prose — the cost
// is one short line, and the alternative is a rule about when to render a fact, which is
// how facts stop being rendered.
//
// ONE ITEM PER `<li>`, not a joined string: these are repo-controlled names, a filename
// may contain a comma or a newline on every filesystem this runs on, and a delimiter that
// a name can contain is a name that can forge two entries. The element boundary cannot be
// typed into a filename. (React escapes the text itself, so this is about reading, not
// injection.)
//
// The label is the only word this composes, which is the §4b line for a screen that
// otherwise renders the server verbatim.
//
// R13-ARCH-A — RENDERED FROM ANY TIER, AND THAT IS WIDER THAN THE SCANNER'S VOUCHING
// RULE ON PURPOSE. `scanner.core.ANNOUNCEMENT_TIERS` lets only a blocker or a warning
// vouch for a refusal, because vouching DELETES another check's line and a fact on an
// `ok` row is a fact nobody is told. Rendering deletes nothing: a `refused_paths` list on
// any check is a list of files the scan did not read, and showing it can only add truth
// to the screen.
//
// The asymmetry is the point — permissive where it can only inform, strict where it can
// remove — and it is also what makes this component safe against reports it did not
// produce: a stored `scan_report` from another version, or a check family that grows the
// field later, renders its refusals here whatever tier it chose, rather than this screen
// quietly dropping a list because the tier was not one of two. Narrowing the render to
// match the guard would mean the screen hiding something the report contains, which is
// the opposite direction from every finding this field exists because of.
export function CheckBody({ check }) {
  const refused = check.refused_paths || [];
  return (
    <>
      {check.detail && <p style={PRE_LINE}>{check.detail}</p>}
      {!!refused.length && (
        <div style={{ margin: "6px 0", color: "#e3b341" }}>
          Did not read:
          <ul style={{ margin: "2px 0 0", paddingLeft: "1.4em" }}>
            {refused.map((path) => <li key={path}>{path}</li>)}
          </ul>
        </div>
      )}
      {check.fix_hint &&
        <p style={{ ...PRE_LINE, color: "#8b949e" }}>Fix: {check.fix_hint}</p>}
    </>
  );
}

// R9-5: the three things an empty section list can mean, told apart.
//
// "No findings" was rendered whenever every tier was empty — including for a project
// whose `scan_report` is `{}`, where nothing has been LOOKED at. A green check and "this
// project is ready to configure" on a repository no scanner has read is the strongest
// false reassurance this screen can give, and the wizard directly below it refuses that
// same project with `scan_required`: two panels, one screen, opposite claims.
//
// `scanned_at` is the discriminator because it is the one field that says a scan
// happened, and it comes from the project row rather than from the report's contents —
// an empty report and an absent one are indistinguishable by their check lists.
export function reportSummary(report) {
  const r = report || {};
  const sections = [
    ["blocker", r.blockers], ["warning", r.warnings],
    ["advice", r.advice], ["pending_sandbox", r.pending_sandbox || []],
  ];
  if (sections.some(([, checks]) => checks?.length)) return { kind: "findings", sections };
  return { kind: r.scanned_at ? "clean" : "never-scanned", sections };
}

// R9-7: the reason is TEXT, not only a tooltip.
//
// `title=` on a DISABLED button reaches a pointer hovering it and nobody else: the
// element is not focusable, so keyboard and screen-reader users never meet it, and on a
// touch screen there is no hover at all. For most refusals the panel above happened to
// repeat the reason — the blockers are listed as findings — but for `scan_required` and
// the R8-2 schema-skew refusal there is nothing above: the report is empty (or refused),
// so the tooltip was the whole explanation of a button that will not move.
//
// The text is `gate.title`, which materializeGate takes verbatim from `state.blocking`,
// so the §4b pin still holds — this renders the server's sentence in a second place, it
// does not compose a new one. The `title=` stays for the pointer.
export function MaterializeControl({ gate, busy, onClick, id = "materialize" }) {
  // R10-UX-F7: the visible reason is WIRED to the button, not merely near it.
  //
  // R9-7 put the refusal on screen because `title=` on a disabled button reaches a
  // hovering pointer and nobody else. That fixed the sighted keyboard user and left the
  // screen-reader one: a paragraph after a button is a paragraph after a button, and
  // nothing said the two were about each other. `aria-describedby` says it — the button
  // announces its label and then its reason, which is the order a reader needs them in.
  //
  // The `title=` stays for the pointer. `id` is a prop rather than a constant because
  // this control renders once per site on a project with several, and duplicate ids
  // would point every button at the first one's reason.
  const reasonId = `${id}-reason`;
  const shown = gate.disabled && !!gate.title;
  const off = busy || gate.disabled;
  return (
    <>
      <button style={disabledBox(off)} disabled={off} onClick={onClick}
        aria-busy={busy} title={gate.title}
        aria-describedby={shown ? reasonId : undefined}>
        {gate.label}</button>
      {shown &&
        <p id={reasonId} style={{ color: "#e3b341", margin: "6px 0" }}>{gate.title}</p>}
    </>
  );
}

// R12-F12-3: the label does not move while the request is in flight.
//
// It read "…" — three characters where a sentence had been — so the control an operator
// had just pressed lost its accessible NAME mid-action: a screen reader that re-reads the
// focused element announces an ellipsis, and a sighted operator loses the only text
// saying what the button does. `MaterializeControl` keeps `gate.label` throughout and
// always has, so this screen said "working" two different ways depending on which button
// you pressed.
//
// `aria-busy` is the part that actually says it to a reader, and it is on both controls
// now. The visible signal is `disabledBox` (R11-UX-F5), which the button already wears
// while the request is in flight.
//
// Extracted for readiness-render.test.ts's reason, the same one `MaterializeControl` was
// extracted under: the only way to assert markup is to render it, and everything else in
// `SiteWizard` fetches.
export function SaveButton({ busy, disabled, onClick }) {
  return (
    <button style={disabledBox(disabled)} disabled={disabled} aria-busy={!!busy}
      onClick={onClick}>Save answers</button>
  );
}

// R10-UX-F6: consent to a list, not to nothing.
//
// The checkbox rendered unconditionally. On takko/prod — a clean project with an empty
// `state.warnings` — the operator was shown "I have read the warnings above and accept
// them" with no warnings anywhere on the screen, and ticking it sent
// `confirm_warnings: true` to a server that had asked for no such thing. A consent
// control for an empty set is not a small cosmetic problem: it trains the operator to
// tick it, which is the exact habit the one screen that DOES gate on it needs them not
// to have.
//
// AND IT NAMES WHAT IS BEING ACCEPTED. "The warnings above" pointed at a report panel
// that lists every tier; `state.warnings` is the server's own narrower list — the checks
// `materialize` will refuse over — and those two are not the same set. The titles come
// from the payload, so this composes no copy of its own (§4b).
export function WarningsAck({ warnings, checked, onChange }) {
  const items = warnings || [];
  if (!items.length) return null;
  return (
    <label>
      <input type="checkbox" checked={checked} onChange={onChange} />
      {" "}I have read {items.length === 1 ? "this warning" : `these ${items.length} warnings`}
      {" "}and accept {items.length === 1 ? "it" : "them"}:{" "}
      <span style={{ color: "#e3b341" }}>{items.map((w) => w.title).join("; ")}</span>
    </label>
  );
}

// R10-UX-F7 / F8: what the server said back, in one announced region.
//
// EVERY outcome of pressing a button in this form lands here — "Saved.", a validation
// error, and the 409 refusal panel — and all three are text that appears where the
// operator is not looking, because they are looking at the button they pressed.
// `role="status"` + `aria-live="polite"` is what makes a change here ANNOUNCED rather
// than merely present; without it the only feedback for any of the three is visual.
// Polite rather than assertive: it may wait for a pause in speech, and none of these
// interrupt a task in progress.
//
// The region is always in the DOM, with its contents swapped inside it. A live region
// that MOUNTS carrying its message is one most screen readers announce nothing for —
// they watch an existing region for changes — so an outer <div> that comes and goes
// with the message would be the markup for a feature that does not work.
//
// Extracted rather than left inline for readiness-render.test.ts's reason: the only way
// to assert markup is to render it, and everything else in `SiteWizard` fetches.
export function OutcomeRegion({ msg }) {
  return (
    <div role="status" aria-live="polite">
      {msg?.ok && <p style={{ color: "#3fb950" }}>{msg.text}</p>}
      {msg?.ok === false && <p style={{ color: "#ff7b72" }}>{msg.text}</p>}
      {msg?.problems && (
        <div style={{ color: "#e3b341" }}>
          <p>Materialization refused — every reason, not just the first:</p>
          <ul>{msg.problems.map((p, i) => (
            <li key={i}><strong>{p.code}</strong>: {p.detail}
              {!!p.items?.length && <ul>{p.items.map((it, j) =>
                <li key={j}>{it.prompt || it.title || it.id}</li>)}</ul>}
            </li>))}
          </ul>
          {/* Said once, here, because the panel above visibly changes under the operator
              when this happens and an unexplained change is its own defect.
              R10-UX-F8: it used to read "…re-read from the server AFTER THIS ANSWER",
              and the refusal it is most often read under is `warnings_unconfirmed` —
              which arrives when the operator pressed Materialize having answered
              nothing. The sentence told them an answer they did not give had been taken
              into account. The re-read is the fact being explained, it happens on every
              409 regardless, and the clause naming a cause this component cannot know
              is gone. */}
          <p style={{ color: "#8b949e" }}>The report and this form were re-read from the
            server, so what you see above is its current state.</p>
        </div>
      )}
    </div>
  );
}

function Stamp({ at }) {
  if (!at) return <span style={{ color: "#8b949e" }}>never scanned</span>;
  return <span style={{ color: "#8b949e" }}>data as of {new Date(at).toLocaleString()}</span>;
}

// R10-UX-F1: the left column's row, and the same distinction R9-5 drew in the panel.
//
// It used to be written inline inside ReadinessScreen's `.map`, which is why it had no
// render pin: nothing in this file was reachable from a test without mounting a
// component that fetches. Extracted for the same reason `Badge`, `CheckBody` and
// `MaterializeControl` are — the only way to assert markup is to render it.
//
// THE DEFECT: `Object.values(p.tiers).every((n) => n === 0)` is true for a project
// whose `scan_report` is `{}`, so a repository no scanner has read rendered
//
//     orders-api  ✓ clean  never scanned
//
// one column away from a panel reading "⏳ Not scanned yet — this project has no
// readiness report, which is not the same as having nothing to report." R9-5 fixed
// exactly this sentence in the panel and did not reach the list, so the screen went on
// making both claims at once — and the row is the half the operator reads FIRST, while
// deciding which project to open.
//
// `scanned_at` is the discriminator, for R9-5's reason: it is the one field that says a
// scan happened, and a tier count of zero cannot tell "nothing found" from "nothing
// looked at". The never-scanned arm says so in the words the panel already uses, so the
// two halves of the screen agree rather than merely not contradicting each other.
export function ProjectRow({ project: p }) {
  const scanned = !!p.scanned_at;
  const nothingFound = Object.values(p.tiers).every((n) => n === 0);
  return (
    <>
      <strong>{p.name}</strong>
      <div>{Object.entries(p.tiers).map(([t, n]) => n > 0 && <Badge key={t} tier={t} n={n} />)}
        {nothingFound && (scanned
          ? <span style={{ color: "#3fb950" }}>✓ clean</span>
          : <span style={{ color: "#8b949e" }}>⏳ not scanned</span>)}
      </div>
      <div><Stamp at={p.scanned_at} /></div>
      {p.sites.map((s) => (
        <div key={s.id} style={{ marginTop: 4, fontSize: "0.9em" }}>
          {s.name}{s.domain ? ` — ${s.domain}` : ""} ·{" "}
          {s.latest_manifest_version == null
            ? <span style={{ color: "#8b949e" }}>no manifest yet</span>
            : s.manifest_current
              ? <span style={{ color: "#3fb950" }}>✓ manifest v{s.latest_manifest_version} matches current scan</span>
              : <span style={{ color: "#e3b341" }}>⚠ manifest v{s.latest_manifest_version} predates current scan</span>}
        </div>
      ))}
    </>
  );
}

// R11-UX-F4: the left column's rows are a keyboard control, and were one by half.
//
// `role="button"` is a PROMISE about behaviour: a thing so labelled is expected to
// activate on Enter AND on Space, and to say whether it is currently the chosen one. The
// row handled Enter only — so a keyboard operator pressing Space (the key most people
// reach for on something that calls itself a button) scrolled the page instead of opening
// the project, with no feedback of any kind. And selection was communicated by an
// `outline` and nothing else: invisible to a screen reader, and a colour to everyone
// else, which is the arrangement §F9 forbids for status and is no better for state.
//
// NOT CONVERTED TO A REAL <button>, and the reason is the markup rather than preference:
// a `<button>`'s content model is PHRASING content, and this row is a block — tier
// badges in a `<div>`, the staleness stamp in another, one line per site. Browsers
// reparent invalid nesting, so the honest options were "flatten the row into spans" or
// "keep role=button and honour the whole contract". The second is smaller and touches no
// markup a reviewer has already read.
export function rowActivates(event) {
  // " " is the modern spelling; "Spacebar" is IE/Edge-legacy and costs one comparison.
  return event.key === "Enter" || event.key === " " || event.key === "Spacebar";
}

// The handler itself, named so a test can call it: `renderToStaticMarkup` produces no
// events, and an `onKeyDown` written inline in JSX is unreachable from this tree's
// runner. `preventDefault` is half the fix — Space on a focused element scrolls the page,
// which is what it did instead of selecting, and a selection that also scrolls is a
// selection the operator has to go and find.
export function rowKeyHandler(onSelect) {
  return (event) => {
    if (!rowActivates(event)) return;
    event.preventDefault();
    onSelect();
  };
}

export function ProjectRowSelector({ project, selected, onSelect }) {
  return (
    <div style={{ ...box, marginBottom: 8, cursor: "pointer",
        outline: selected ? "2px solid #58a6ff" : "none" }}
      role="button" tabIndex={0} aria-pressed={selected}
      onClick={onSelect} onKeyDown={rowKeyHandler(onSelect)}>
      {/* The non-colour half of the selection signal. `aria-hidden` because
          `aria-pressed` already says this to a screen reader, and two spellings of one
          fact is what R10-UX-F7 took out of `Badge`.

          R12-F12-4: the span is rendered in BOTH states and reserves its width. Added
          only when selected, it shifted the project's name sideways on every click —
          the row the operator is reading moves under the cursor at the moment they
          choose it, and on a keyboard walk down the list every row jumps in turn. */}
      <span aria-hidden="true"
        style={{ display: "inline-block", width: "1.1em" }}>{selected ? "▸" : ""}</span>
      <ProjectRow project={project} />
    </div>
  );
}

export default function ReadinessScreen() {
  const [projects, setProjects] = useState(undefined); // undefined = loading
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  // R9-4: bumped when a write (or a refusal) means the panel's report is out of date.
  // A prop rather than a call, because the panel owns its own fetch.
  const [refreshKey, setRefreshKey] = useState(0);

  // `quiet` re-reads WITHOUT emptying the screen first. The loud version is right on
  // first paint and on Retry — there is nothing to show, so show the spinner — and wrong
  // after a materialize: it unmounts the wizard, and with it the refusal the operator is
  // reading and the answers they have typed. The refusal that triggers the re-read would
  // be the first thing destroyed by it.
  const load = ({ quiet = false } = {}) => {
    setError("");
    if (!quiet) setProjects(undefined);
    api("v1/projects/").then(({ status, data }) => {
      if (status === 200) setProjects(data);
      else setError(data.detail || `Could not load projects (HTTP ${status})`);
    });
  };
  useEffect(() => { load(); }, []);

  // What a site's wizard calls when the server's answer means this screen is stale.
  const refresh = () => { load({ quiet: true }); setRefreshKey((k) => k + 1); };

  // R12-F12-1: Retry unmounts the button that was pressed.
  //
  // The error panel is a message and a Retry button; pressing it swaps the whole panel
  // for "Loading projects…", so the focused element ceases to exist and focus falls to
  // `<body>`. For a screen-reader user that is the entire feedback for the press: nothing
  // is announced, and the next Tab starts from the top of the document. If the retry fails
  // again, the error text they were meant to read is not announced either.
  //
  // `retried` gates it so first paint does not steal focus — nobody pressed anything, and
  // moving focus on load is its own defect. Both swap targets carry the ref, because which
  // one renders next is the server's answer, not this component's choice.
  const statusRef = useRef(null);
  const [retried, setRetried] = useState(false);
  useEffect(() => {
    if (retried) statusRef.current?.focus();
  }, [retried, projects === undefined, error]);

  if (error)
    return (
      <div style={{ padding: 16 }}>
        <p ref={statusRef} tabIndex={-1} style={{ color: "#ff7b72" }}>{error}</p>
        <button style={box} onClick={() => { setRetried(true); load(); }}>Retry</button>
      </div>
    );
  // NOT FOCUSED, and it is the same judgement in the other direction: when the retry
  // SUCCEEDS this paragraph is replaced by the project list, and `statusRef` is null, so
  // nothing is focused and the operator's focus is back at the top of a screen that now
  // has content. Moving it into a data region unasked interrupts whatever the reader is
  // saying with a heading nobody requested. The failure path is the one where the
  // feedback is otherwise silent.
  if (projects === undefined)
    return <p ref={statusRef} tabIndex={-1} style={{ padding: 16 }}>Loading projects…</p>;
  if (!projects.length)
    return (
      <div style={{ padding: 16 }}>
        <h3>No projects yet</h3>
        <p>Add a project via <code>POST /api/v1/projects/</code> or the CLI, then scan
          it: <code>python -m hub scan &lt;path&gt;</code>. It will appear here with its
          readiness report.</p>
      </div>
    );

  return (
    <div style={{ display: "flex", gap: 16, padding: 16, alignItems: "flex-start" }}>
      <div style={{ minWidth: 280 }}>
        <h3 style={{ marginTop: 0 }}>Projects</h3>
        {projects.map((p) => (
          <ProjectRowSelector key={p.id} project={p} selected={selected === p.id}
            onSelect={() => setSelected(p.id)} />
        ))}
      </div>
      {selected != null && <ReadinessPanel projectId={selected}
        project={projects.find((p) => p.id === selected)}
        refreshKey={refreshKey} onChanged={refresh} />}
    </div>
  );
}

function ReadinessPanel({ projectId, project, refreshKey, onChanged }) {
  const [report, setReport] = useState(undefined);
  const [error, setError] = useState("");

  // Selecting a different project empties the panel; a refresh of the SAME project does
  // not (R9-4). Two effects because they are two events: the first is "this is a
  // different thing now, show nothing until it arrives", the second is "read it again",
  // and a refresh that cleared the report would take the wizard and its refusal with it.
  useEffect(() => { setReport(undefined); setError(""); }, [projectId]);
  useEffect(() => {
    let current = true;
    api(`v1/projects/${projectId}/readiness/`).then(({ status, data }) => {
      if (!current) return;   // a slow response for a project the operator left
      if (status === 200) { setReport(data); setError(""); }
      else setError(data.detail || `Could not load report (HTTP ${status})`);
    });
    return () => { current = false; };
  }, [projectId, refreshKey]);

  if (error) return <p style={{ color: "#ff7b72" }}>{error}</p>;
  if (report === undefined) return <p>Loading report…</p>;

  const { kind, sections } = reportSummary(report);
  return (
    <div style={{ flex: 1 }}>
      <h3 style={{ marginTop: 0 }}>Readiness — {project?.name}
        {" "}<small><Stamp at={report.scanned_at} /></small></h3>
      <ReportScope report={report} />
      {kind === "clean" &&
        <p style={{ color: "#3fb950" }}>✓ No findings. This project is ready to configure.</p>}
      {kind === "never-scanned" && (
        <div style={{ color: "#8b949e" }}>
          <p style={{ color: "#e6e6e6" }}>⏳ Not scanned yet — this project has no
            readiness report, which is not the same as having nothing to report.</p>
          <p>Run <code>python -m hub scan &lt;path&gt;</code> (or the scan endpoint) and
            this panel fills in. Until then the wizard below cannot materialize a
            manifest, and says so in the server's own words.</p>
        </div>
      )}
      {sections.map(([tier, checks]) => !!checks?.length && (
        <section key={tier} style={{ marginBottom: 12 }}>
          <h4><Badge tier={tier} n={checks.length} /></h4>
          {checks.map((c) => (
            <details key={c.id} style={{ ...box, marginBottom: 6 }}>
              <summary>{c.title}</summary>
              <CheckBody check={c} />
            </details>
          ))}
        </section>
      ))}
      {project?.sites?.map((s) => (
        <SiteWizard key={s.id} site={s} refreshKey={refreshKey} onChanged={onChanged} />
      ))}
    </div>
  );
}

// R11-UX-F2: one question, one input, and an id nothing else on the page shares.
//
// THE DEFECT: the field carried `id={q.id}` and the label `htmlFor={q.id}`, and a project
// page renders ONE WIZARD PER SITE. takko has two, and both wizards ask `site.domain` —
// so the page contained two elements with `id="site.domain"`, which is invalid HTML with
// a defined and unhelpful resolution: `getElementById` and every label point at the FIRST
// one. Clicking "Public domain for this site" under `staging` focused `prod`'s box.
// Typing then went into the wrong site's form, and the operator's only clue was that the
// caret was somewhere else on the screen.
//
// The prefix is the site's pk, which is the same key `MaterializeControl`'s `id` prop
// already uses for the same reason ("this control renders once per site on a project with
// several, and duplicate ids would point every button at the first one's reason"). One
// rule, spelled once, in a function both the field and the label read.
//
// Extracted for readiness-render.test.ts's reason as well: the only way to assert markup
// is to render it, and everything else in `SiteWizard` fetches.
export const questionFieldId = (siteId, questionId) => `site-${siteId}-${questionId}`;

export function QuestionField({ siteId, question: q, prior, drafted, onChange }) {
  const id = questionFieldId(siteId, q.id);
  const priorText = typeof prior === "object" ? "" : prior ?? "";
  return (
    <div style={{ marginBottom: 8 }}>
      <label htmlFor={id}>{q.prompt}
        {q.kind === "secret" && prior?.answered &&
          <em style={{ color: "#8b949e" }}> — set {new Date(prior.changed_at).toLocaleDateString()}; leave blank to keep</em>}
      </label><br />
      {q.kind === "choice"
        ? <select id={id} style={box} value={drafted ?? priorText}
            onChange={(e) => onChange(e.target.value)}>
            <option value="" disabled>choose…</option>
            {q.choices.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        : q.kind === "bool"
        ? <input id={id} type="checkbox" checked={drafted ?? prior ?? false}
            onChange={(e) => onChange(e.target.checked)} />
        : <input id={id} style={{ ...box, width: "60%" }}
            type={q.kind === "secret" ? "password" : "text"}
            autoComplete={q.kind === "secret" ? "new-password" : "off"}
            value={drafted ?? (q.kind === "secret" ? "" : priorText)}
            onChange={(e) => onChange(e.target.value)} />}
    </div>
  );
}

// R11-Q1: what this form SENDS and what it does with the answer, outside the component.
//
// THE DEAD ZONE. `materializeGate` and `materializeOutcome` were extracted in rounds 8
// and 9 because a decision inside a component is a decision no test can look at — and
// the two handlers that USE them stayed inside, where the same argument applies with more
// force: they are the only code on this screen that composes a request body. Two
// mutations, applied to the shipped file, survived all 79 tests:
//
//   * `{ confirm_warnings: … }` renamed to `{ ack: … }` — the ack checkbox stops
//     reaching the server entirely, so the one control the warnings gate exists for does
//     nothing and the POST is refused (or accepted) for reasons unrelated to it;
//   * `if (outcome.reloadWizard) load();` deleted — the R9-4 convergence, which is the
//     whole of round 9's item 4, silently gone: the 409 panel goes back to sitting above
//     a wizard state the server has just contradicted.
//
// The fixtures cannot catch either, because the fixtures are the server: they answer
// what they are asked and never see what the client failed to ask for. So the handlers
// take their collaborators as arguments and the test drives them with a spy in `api`'s
// place. `SiteWizard` stays thin — it owns the state hooks and hands them over.
export function makeWizardHandlers({ siteId, state, draft, ack, load, onChanged,
                                     setBusy, setMsg, setDraft, api: call = api }) {
  async function save() {
    setBusy(true); setMsg(null);
    const { status, data } = await call(`v1/sites/${siteId}/wizard/`, draft, "PATCH");
    setBusy(false);
    if (status === 200) { setDraft({}); load(); setMsg({ ok: true, text: "Saved." }); }
    else setMsg({ ok: false, text: Object.entries(data).map(([f, e]) =>
      `${f}: ${Array.isArray(e) ? e.map((x) => x.message || x).join(", ") : e}`).join(" · ") });
  }

  async function materialize() {
    setBusy(true); setMsg(null);
    // R10-UX-F6: no warnings, no consent — whatever `ack` happens to hold. The checkbox
    // is not rendered in that case, so this can only differ after the server's warnings
    // go away under an operator who already ticked it, and sending `true` there is
    // confirming a set that no longer exists.
    const { status, data } = await call(`v1/sites/${siteId}/manifest/`,
      { confirm_warnings: !!state?.warnings?.length && ack });
    setBusy(false);
    const outcome = materializeOutcome(status, data);
    setMsg(outcome.msg);
    // Both re-reads are quiet: the message above stays put while the screen underneath
    // it catches up with the server (R9-4).
    if (outcome.reloadWizard) load();
    if (outcome.refreshProject) onChanged();
  }

  return { save, materialize };
}

function SiteWizard({ site, refreshKey, onChanged }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState(undefined);
  const [draft, setDraft] = useState({});
  const [ack, setAck] = useState(false);
  const [msg, setMsg] = useState(null); // {ok, text} | {problems}
  const [busy, setBusy] = useState(false);
  const openedRef = useRef(null);

  const load = () =>
    api(`v1/sites/${site.id}/wizard/`).then(({ status, data }) =>
      setState(status === 200 ? data : { error: data.detail || `HTTP ${status}` }));
  // R11-UX-F3: `refreshKey` is in the deps, and it is a sibling's convergence that puts
  // it there. A 409 on ONE site means the project's stored report moved — that is what
  // the refusal says — and every other open wizard on the page is then showing preflight
  // answers computed against the report from before it moved. The panel above them
  // re-read (it has taken `refreshKey` since R9-4); the wizards did not, so the screen
  // held a blocker list and a sibling gate saying the deploy may proceed at the same
  // time. Same prop, same reason, one component further down.
  useEffect(() => { if (open) load(); }, [open, refreshKey]);

  const { save, materialize } = makeWizardHandlers({
    siteId: site.id, state, draft, ack, load, onChanged, setBusy, setMsg, setDraft,
  });

  // R12-F12-1: where the keyboard is after the button that was there is gone.
  //
  // "Configure & materialize" REPLACES itself with the form — the collapsed button is
  // unmounted by the click that opens it. The element that had focus no longer exists, so
  // the browser drops focus to `<body>`: a screen-reader user hears nothing about the form
  // that just appeared, and the next Tab starts again from the top of the document, above
  // the project list, several stops from the thing they opened.
  //
  // `tabIndex={-1}` makes the container programmatically focusable without adding a tab
  // stop, which is the standard treatment for a region that receives focus after an
  // action. Focusing the CONTAINER rather than the first input is deliberate: the heading
  // and the question list are read from there, and landing on the first field would skip
  // the form's own name.
  //
  // All three post-open renders take the ref — the form, the "Loading wizard…" spinner and
  // the error line — because the fetch is in flight when the click lands, so which of them
  // exists at that moment depends on the network. A ref on only the happy one focuses
  // nothing exactly when the operator has least information.
  useEffect(() => { if (open) openedRef.current?.focus(); }, [open, state === undefined]);

  if (!open)
    return <button style={{ ...box, marginTop: 6 }} onClick={() => setOpen(true)}>
      Configure &amp; materialize — {site.name}</button>;
  if (state === undefined) return <p ref={openedRef} tabIndex={-1}>Loading wizard…</p>;
  if (state.error)
    return <p ref={openedRef} tabIndex={-1} style={{ color: "#ff7b72" }}>{state.error}</p>;

  const unanswered = state.questions.filter((q) => !(q.id in (state.answered || {})));
  const gate = materializeGate(state);
  return (
    <div ref={openedRef} tabIndex={-1} style={{ ...box, marginTop: 8 }}>
      <h4 style={{ marginTop: 0 }}>{site.name} — configuration</h4>
      {state.questions.map((q) => (
        <QuestionField key={q.id} siteId={site.id} question={q}
          prior={state.answered?.[q.id]} drafted={draft[q.id]}
          onChange={(value) => setDraft({ ...draft, [q.id]: value })} />
      ))}
      <SaveButton busy={busy} disabled={busy || !Object.keys(draft).length}
        onClick={save} />{" "}
      <WarningsAck warnings={state.warnings} checked={ack}
        onChange={(e) => setAck(e.target.checked)} />{" "}
      <MaterializeControl gate={gate} busy={busy} onClick={materialize}
        id={questionFieldId(site.id, "materialize")} />
      {!!unanswered.length &&
        <p style={{ color: "#8b949e" }}>{unanswered.length} question{unanswered.length === 1 ? "" : "s"} unanswered</p>}
      <OutcomeRegion msg={msg} />
    </div>
  );
}
