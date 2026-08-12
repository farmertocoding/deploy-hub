// F7-lite (Phase 1): project list → three-tier readiness report → wizard → materialize.
// Same plain-React idiom as App.jsx — shadcn/Tailwind (§A8) still deferred; mockup
// first per the working agreement, styling later on request.
//
// §F9 rules applied here: status is never color-only (every tier carries a symbol +
// word); dark palette matches Phase 0; every data panel carries its staleness stamp.
// §F8: the five states (empty/loading/live/error/degraded) are reachable without a
// backend via ?sim=<state> — see sim.js, and the contract test that pins the fixtures
// to the generated zod schemas.
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
// operation pinned to change nothing. Pinned by tests/materialize-gate.test.ts.
export function materializeGate(state) {
  const blocking = state?.blocking || [];
  const codes = blocking.map((p) => p.code);
  if (state?.can_materialize)
    return { disabled: false, label: "Materialize manifest", title: "" };
  if (codes.includes("blockers_present"))
    return {
      disabled: true, label: "⛔ Blocked",
      title: "Blockers must be fixed and rescanned first — materialization will refuse.",
    };
  if (codes.length && codes.every((c) => c === "answers_missing"))
    return {
      disabled: true, label: "Answer required",
      // Not "fix and rescan": a declaration confirm is cleared by answering it here,
      // and a re-scan of an unchanged tree produces the identical report forever.
      title: "Some required questions are unanswered — including any declaration you " +
        "must accept or refuse. Answering them here is what clears them; re-scanning " +
        "will not.",
    };
  return {
    disabled: true, label: "⛔ Blocked",
    title: blocking.map((p) => p.detail).filter(Boolean).join(" · "),
  };
}

function Stamp({ at }) {
  if (!at) return <span style={{ color: "#8b949e" }}>never scanned</span>;
  return <span style={{ color: "#8b949e" }}>data as of {new Date(at).toLocaleString()}</span>;
}

export default function ReadinessScreen() {
  const [projects, setProjects] = useState(undefined); // undefined = loading
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  const load = () => {
    setError("");
    setProjects(undefined);
    api("v1/projects/").then(({ status, data }) => {
      if (status === 200) setProjects(data);
      else setError(data.detail || `Could not load projects (HTTP ${status})`);
    });
  };
  useEffect(load, []);

  if (error)
    return (
      <div style={{ padding: 16 }}>
        <p style={{ color: "#ff7b72" }}>{error}</p>
        <button style={box} onClick={load}>Retry</button>
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
        project={projects.find((p) => p.id === selected)} onChanged={load} />}
    </div>
  );
}

function ReadinessPanel({ projectId, project, onChanged }) {
  const [report, setReport] = useState(undefined);
  const [error, setError] = useState("");

  useEffect(() => {
    setReport(undefined);
    setError("");
    api(`v1/projects/${projectId}/readiness/`).then(({ status, data }) => {
      if (status === 200) setReport(data);
      else setError(data.detail || `Could not load report (HTTP ${status})`);
    });
  }, [projectId]);

  if (error) return <p style={{ color: "#ff7b72" }}>{error}</p>;
  if (report === undefined) return <p>Loading report…</p>;

  const sections = [
    ["blocker", report.blockers], ["warning", report.warnings],
    ["advice", report.advice], ["pending_sandbox", report.pending_sandbox || []],
  ];
  return (
    <div style={{ flex: 1 }}>
      <h3 style={{ marginTop: 0 }}>Readiness — {project?.name}
        {" "}<small><Stamp at={report.scanned_at} /></small></h3>
      {sections.every(([, checks]) => !checks?.length) &&
        <p style={{ color: "#3fb950" }}>✓ No findings. This project is ready to configure.</p>}
      {sections.map(([tier, checks]) => !!checks?.length && (
        <section key={tier} style={{ marginBottom: 12 }}>
          <h4><Badge tier={tier} n={checks.length} /></h4>
          {checks.map((c) => (
            <details key={c.id} style={{ ...box, marginBottom: 6 }}>
              <summary>{c.title}</summary>
              {c.detail && <p>{c.detail}</p>}
              {c.fix_hint && <p style={{ color: "#8b949e" }}>Fix: {c.fix_hint}</p>}
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
    if (status === 201) { setMsg({ ok: true, text: `Manifest v${data.version} created.` }); onChanged(); }
    else if (status === 409) setMsg({ problems: data.problems || [data] });
    else setMsg({ ok: false, text: data.detail || `HTTP ${status}` });
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
        </div>
      )}
    </div>
  );
}
