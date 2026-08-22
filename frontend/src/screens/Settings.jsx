// Settings (§F1): the non-object surfaces, as TABS — Developer (the Phase-0 demo
// pane, which is a plumbing proof and not the product surface) and Vault (a Settings
// tab until Phase 4 gives it a real screen). The Cloudflare-connect panel is Task
// 12b's tab and is deliberately absent here.
//
// The demo pane is otherwise the Phase-0 code moved verbatim, with two changes:
// it takes the shell's ONE events client as a prop instead of opening a second
// socket, and its Launch goes through the §F5 tier machinery — demo.launch is a T2
// row, so the confirm dialog summarizing what will run is the live wiring of the
// tier table to the one mutating action the product has today.
import React, { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { schemas } from "../api/zod.ts";
import { api } from "../api.js";
import { presentation, tierFor } from "../actions.js";
import { ConfirmDialog } from "../Tiers.jsx";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export const SETTINGS_TABS = [
  { id: "developer", label: "Developer" },
  { id: "vault", label: "Vault" },
];

export default function Settings({ user, events }) {
  const [tab, setTab] = useState("developer");
  return (
    <div style={{ padding: 16 }}>
      <nav style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        {SETTINGS_TABS.map((t) => (
          <button key={t.id} style={{ ...box, opacity: tab === t.id ? 1 : 0.6 }}
            onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </nav>
      {tab === "developer"
        ? <DemoPanel user={user} events={events} />
        : <p style={{ color: "#8b949e" }}>Vault management gets its screen in Phase 4;
            until then secrets stay CLI-managed and this tab says so.</p>}
    </div>
  );
}

// §4.5 client half: the generated zod mirror (frontend/src/api/zod.ts) validates
// before the wire; the DRF serializer stays the source of truth. Friendly copy for
// zod's generic messages lives here — the rules themselves are never hand-written.
const demoJobErrorMap = (issue, ctx) => {
  if (issue.path[0] === "name") {
    return { message: "Lowercase letters, digits and dashes; start with a letter." };
  }
  if (issue.path[0] === "delay") {
    return { message: "Delay must be between 0.05 and 5.0 seconds." };
  }
  return { message: ctx.defaultError };
};

function snapshotFailedLine(status) {
  if (status === 403) return "⚠ snapshot refused — session expired? Log in again.";
  return "⚠ snapshot refetch failed — will retry on next reconnect.";
}

export function DemoPanel({ user, events }) {
  const { status, subscribe, unsubscribe } = events;
  const [lines, setLines] = useState([]);
  // The pane shows one mode at a time; switching modes unsubscribes the previous
  // topics so stale streams can't interleave and snapshots can't clobber the
  // other mode's lines (round-3 finding). A ref, not state: an async launch
  // resolving after a mode switch must swap the ACTUAL current topics, not a
  // click-time closure (round-4 finding).
  const paneTopicsRef = useRef([]);
  function takePane(topics) {
    paneTopicsRef.current.forEach((t) => unsubscribe(t));
    paneTopicsRef.current = topics;
  }
  const [warnings, setWarnings] = useState(null);
  const [busy, setBusy] = useState(false); // covers the 409-confirm relaunch too
  // §F5: demo.launch is T2, so the click lands in a confirm carrying the summary of
  // what will run — table-driven, so demoting the row demotes the dialog with it.
  const [pending, setPending] = useState(null);
  const {
    register,
    handleSubmit,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(schemas.DemoJob, { errorMap: demoJobErrorMap }),
    defaultValues: { name: "demo", delay: 0.5, confirm_warnings: false },
  });

  // Snapshot-then-stream (§D7): same fetch on first load and on every reconnect.
  // Non-OK snapshot responses carry their status into the failure line.
  const snapshotFn = async (topic) => {
    const { status: st, data } = await api(`topics/${topic}/snapshot/`);
    // Shape-validate: a 200 with an unparseable/foreign body must count as a
    // failed snapshot, not crash the repaint (live-demo finding).
    if (st !== 200 || !Array.isArray(data.data)) throw { status: st };
    return data;
  };

  async function launch(values, confirm = false) {
    if (busy) return;
    setBusy(true);
    setWarnings(null);
    clearErrors();
    const { status: st, data } = await api("demo-jobs/", {
      ...values, confirm_warnings: confirm,
    });
    setBusy(false);
    if (st === 400) {
      // Server verdict wins (§4.5): map {field: [{code, message, hint}]} into RHF.
      for (const [field, errs] of Object.entries(data.errors ?? {})) {
        const e = errs[0];
        setError(field, { type: e.code, message: [e.message, e.hint].filter(Boolean).join(" ") });
      }
    } else if (st === 409 && (data.warnings ?? []).length) {
      setWarnings({ values, body: data.warnings });
    } else if (st !== 201) {
      // Non-contract statuses (0 network, 403 CSRF/session, 500…) never go silent.
      setError("root", { type: String(st), message: data.detail ?? `Unexpected ${st} response.` });
    } else {
      takePane([data.topic]);
      const seed = `— launching ${values.name}… waiting for first log line —`;
      setLines([seed]);
      subscribe(
        data.topic,
        (event) => {
          if (event.__snapshot) {
            // §D7 repaint: snapshot data is the capped history [{seq, event}] — a
            // socket killed mid-stream recovers every line published while dead.
            // An EMPTY first snapshot must keep the seed line, not blank the pane
            // (round-5 finding: the happy path regressed the pending-feedback fix).
            return setLines(
              event.data.length ? event.data.map((e) => e.event.line ?? "✔ done") : [seed]
            );
          }
          if (event.__snapshot_failed)
            return setLines((p) => [...p, snapshotFailedLine(event.status)]);
          setLines((p) => [...p, event.line ?? "✔ done"]);
        },
        snapshotFn
      );
    }
  }

  function submit(values) {
    if (presentation(tierFor("demo.launch")).confirm) setPending(values);
    else launch(values, false);
  }

  // §F8 v0: watch the simulation replayer (manage.py replay_simulation) through the
  // same multiplexed socket — two topics, one panel, real publish() path.
  function watchSimulation() {
    takePane(["demo.sim.log", "alerts"]);
    setLines(["— watching simulation topics (run: manage.py replay_simulation) —"]);
    const synced = new Set(); // first snapshot per topic = initial load, not a resync
    const simHandler = (topic, render) => (event) => {
      if (event.__snapshot) {
        const isResync = synced.has(topic);
        synced.add(topic);
        // Append a delimited per-topic block — never replace the shared pane
        // (round-2 finding: one topic's snapshot wiped the other's lines).
        const block = event.data.map((e) => render(e.event));
        if (isResync) return setLines((p) => [...p, `— ${topic} resynced —`, ...block]);
        if (block.length) return setLines((p) => [...p, ...block]);
        return;
      }
      if (event.__snapshot_failed)
        return setLines((p) => [...p, snapshotFailedLine(event.status)]);
      setLines((p) => [...p, render(event)]);
    };
    subscribe("demo.sim.log",
      simHandler("demo.sim.log", (e) => e.line ?? JSON.stringify(e)), snapshotFn);
    subscribe("alerts",
      simHandler("alerts", (e) => `⚠ ${e.kind} ${e.site ?? ""} ${e.state ?? ""}`), snapshotFn);
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <h2>
        Demo job{" "}
        <small style={{ color: status === "live" ? "#7ee787" : "#f0b72f" }}>({status})</small>
      </h2>
      <p>Signed in as {user.username}.</p>
      {status === "auth-required" && (
        <div style={{ color: "#ff7b72" }}>
          Session expired or enrollment required — reload and log in again.
        </div>
      )}
      <form onSubmit={handleSubmit(submit)}
        style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <label style={{ display: "grid", gap: 4 }}>
          <small>job name</small>
          <input {...register("name")} style={box} placeholder="demo"
            aria-invalid={!!errors.name} />
        </label>
        <label style={{ display: "grid", gap: 4 }}>
          <small>delay (s)</small>
          <input {...register("delay", { valueAsNumber: true })} type="number" step="0.05"
            style={{ ...box, width: 80 }} aria-invalid={!!errors.delay} />
        </label>
        <button style={{ padding: 8 }} disabled={isSubmitting || busy}>
          {isSubmitting || busy ? "Launching…" : "Launch"}
        </button>
        <button type="button" onClick={watchSimulation} style={{ padding: 8 }}>
          Watch simulation
        </button>
      </form>
      {pending && (
        <ConfirmDialog label={tierFor("demo.launch").label}
          summary={`Run "${pending.name}" with a ${pending.delay} s delay between lines.`}
          onConfirm={() => { const v = pending; setPending(null); launch(v, false); }}
          onDismiss={() => setPending(null)} />
      )}
      {Object.entries(errors).map(([field, e]) => (
        <div key={field} style={{ color: "#ff7b72", marginTop: 8 }}>
          {field === "root" ? "" : `${field}: `}{e.message}
        </div>
      ))}
      {warnings && (
        <div style={{ color: "#f0b72f", marginTop: 8 }}>
          {warnings.body.map((w) => <div key={w.code}>⚠ {w.message} {w.hint}</div>)}
          <button onClick={() => launch(warnings.values, true)} style={{ marginTop: 8 }}
            disabled={busy}>
            {busy ? "Launching…" : "I understand, continue"}
          </button>
        </div>
      )}
      <pre style={{ background: "#161a21", padding: 12, minHeight: 220, marginTop: 16 }}>
        {lines.join("\n")}
      </pre>
    </div>
  );
}
