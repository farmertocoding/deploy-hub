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
import React, { useEffect, useState } from "react";
import { api } from "./api.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };
const TIER_BADGE = {
  blocker: { sym: "⛔", word: "Blocker", color: "#ff7b72" },
  warning: { sym: "⚠", word: "Warning", color: "#e3b341" },
  advice: { sym: "ℹ", word: "Advice", color: "#79c0ff" },
  pending_sandbox: { sym: "⏳", word: "Deferred to sandbox", color: "#8b949e" },
};

function Badge({ tier, n }) {
  const b = TIER_BADGE[tier];
  // Symbol + word + count: readable colorblind, greyscale, or by screen reader.
  return (
    <span style={{ color: b.color, marginRight: 10 }} aria-label={`${n} ${b.word}`}>
      {b.sym} {n} {b.word}{n === 1 ? "" : "s"}
    </span>
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
  return { disabled: true, label: "⛔ Blocked", title };
}

const ANSWERABLE_REFUSALS = new Set(["answers_missing", "answers_need_reentry"]);

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

export function CheckBody({ check }) {
  return (
    <>
      {check.detail && <p style={PRE_LINE}>{check.detail}</p>}
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

function Stamp({ at }) {
  if (!at) return <span style={{ color: "#8b949e" }}>never scanned</span>;
  return <span style={{ color: "#8b949e" }}>data as of {new Date(at).toLocaleString()}</span>;
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

  if (error)
    return (
      <div style={{ padding: 16 }}>
        <p style={{ color: "#ff7b72" }}>{error}</p>
        <button style={box} onClick={() => load()}>Retry</button>
      </div>
    );
  if (projects === undefined) return <p style={{ padding: 16 }}>Loading projects…</p>;
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
          <div key={p.id} style={{ ...box, marginBottom: 8, cursor: "pointer",
              outline: selected === p.id ? "2px solid #58a6ff" : "none" }}
            role="button" tabIndex={0}
            onClick={() => setSelected(p.id)}
            onKeyDown={(e) => e.key === "Enter" && setSelected(p.id)}>
            <strong>{p.name}</strong>
            <div>{Object.entries(p.tiers).map(([t, n]) => n > 0 && <Badge key={t} tier={t} n={n} />)}
              {Object.values(p.tiers).every((n) => n === 0) && <span style={{ color: "#3fb950" }}>✓ clean</span>}
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
          </div>
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
        <SiteWizard key={s.id} site={s} onChanged={onChanged} />
      ))}
    </div>
  );
}

function SiteWizard({ site, onChanged }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState(undefined);
  const [draft, setDraft] = useState({});
  const [ack, setAck] = useState(false);
  const [msg, setMsg] = useState(null); // {ok, text} | {problems}
  const [busy, setBusy] = useState(false);

  const load = () =>
    api(`v1/sites/${site.id}/wizard/`).then(({ status, data }) =>
      setState(status === 200 ? data : { error: data.detail || `HTTP ${status}` }));
  useEffect(() => { if (open) load(); }, [open]);

  async function save() {
    setBusy(true); setMsg(null);
    const { status, data } = await api(`v1/sites/${site.id}/wizard/`, draft, "PATCH");
    setBusy(false);
    if (status === 200) { setDraft({}); load(); setMsg({ ok: true, text: "Saved." }); }
    else setMsg({ ok: false, text: Object.entries(data).map(([f, e]) =>
      `${f}: ${Array.isArray(e) ? e.map((x) => x.message || x).join(", ") : e}`).join(" · ") });
  }

  async function materialize() {
    setBusy(true); setMsg(null);
    const { status, data } = await api(`v1/sites/${site.id}/manifest/`,
      { confirm_warnings: ack });
    setBusy(false);
    const outcome = materializeOutcome(status, data);
    setMsg(outcome.msg);
    // Both re-reads are quiet: the message above stays put while the screen underneath
    // it catches up with the server (R9-4).
    if (outcome.reloadWizard) load();
    if (outcome.refreshProject) onChanged();
  }

  if (!open)
    return <button style={{ ...box, marginTop: 6 }} onClick={() => setOpen(true)}>
      Configure &amp; materialize — {site.name}</button>;
  if (state === undefined) return <p>Loading wizard…</p>;
  if (state.error) return <p style={{ color: "#ff7b72" }}>{state.error}</p>;

  const unanswered = state.questions.filter((q) => !(q.id in (state.answered || {})));
  const gate = materializeGate(state);
  return (
    <div style={{ ...box, marginTop: 8 }}>
      <h4 style={{ marginTop: 0 }}>{site.name} — configuration</h4>
      {state.questions.map((q) => {
        const prior = state.answered?.[q.id];
        return (
          <div key={q.id} style={{ marginBottom: 8 }}>
            <label htmlFor={q.id}>{q.prompt}
              {q.kind === "secret" && prior?.answered &&
                <em style={{ color: "#8b949e" }}> — set {new Date(prior.changed_at).toLocaleDateString()}; leave blank to keep</em>}
            </label><br />
            {q.kind === "choice"
              ? <select id={q.id} style={box} value={draft[q.id] ?? (typeof prior === "object" ? "" : prior ?? "")}
                  onChange={(e) => setDraft({ ...draft, [q.id]: e.target.value })}>
                  <option value="" disabled>choose…</option>
                  {q.choices.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              : q.kind === "bool"
              ? <input id={q.id} type="checkbox" checked={draft[q.id] ?? prior ?? false}
                  onChange={(e) => setDraft({ ...draft, [q.id]: e.target.checked })} />
              : <input id={q.id} style={{ ...box, width: "60%" }}
                  type={q.kind === "secret" ? "password" : "text"}
                  autoComplete={q.kind === "secret" ? "new-password" : "off"}
                  value={draft[q.id] ?? (q.kind === "secret" ? "" : (typeof prior === "object" ? "" : prior ?? ""))}
                  onChange={(e) => setDraft({ ...draft, [q.id]: e.target.value })} />}
          </div>
        );
      })}
      <button style={box} disabled={busy || !Object.keys(draft).length} onClick={save}>
        {busy ? "…" : "Save answers"}</button>{" "}
      <label>
        <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
        {" "}I have read the warnings above and accept them
      </label>{" "}
      <button style={box} disabled={busy || gate.disabled} onClick={materialize}
        title={gate.title}>
        {gate.label}</button>
      {!!unanswered.length &&
        <p style={{ color: "#8b949e" }}>{unanswered.length} question{unanswered.length === 1 ? "" : "s"} unanswered</p>}
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
          {/* Said once, here, because the panel above visibly changes under the
              operator when this happens and an unexplained change is its own defect. */}
          <p style={{ color: "#8b949e" }}>The report and this form were re-read from the
            server after this answer, so what you see above is its current state.</p>
        </div>
      )}
    </div>
  );
}
