// Phase 0 UI: login (password + TOTP) → forced TOTP enrollment (§6.10 mandatory-2FA)
// → demo log panel on the multiplexed socket. shadcn/Tailwind (§A8) arrive with the
// first real screen; this stays plain so the demo proves plumbing, not styling.
import React, { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { schemas } from "./api/zod.ts";
import { useEvents } from "./useEvents.js";

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return m ? m[2] : "";
}

async function api(path, body) {
  // A down/unreachable server must surface, never reject unhandled (round-1 UX
  // finding): status 0 routes into every existing error branch via data.detail.
  try {
    const res = await fetch(`/api/${path}`, {
      method: body !== undefined ? "POST" : "GET",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
      credentials: "include",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return { status: res.status, data: await res.json().catch(() => ({})) };
  } catch {
    return { status: 0, data: { detail: "Cannot reach server — check your connection and retry." } };
  }
}

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export default function App() {
  // Hydrate the session on load: restores login state across reloads AND plants
  // the CSRF cookie the (CSRF-protected) login POST needs.
  const [user, setUser] = useState(undefined); // undefined = loading
  const [unreachable, setUnreachable] = useState(false);
  const hydrate = () => {
    setUnreachable(false);
    setUser(undefined);
    api("auth/me/").then(({ status, data }) => {
      // A dead server is NOT "logged out" (round-2 finding): show the truth.
      if (status === 0 || status >= 500) return setUnreachable(true);
      setUser(status === 200 && data.authenticated ? data : null);
    });
  };
  useEffect(hydrate, []);
  if (unreachable)
    return (
      <div style={{ margin: "15vh auto", width: "fit-content", textAlign: "center" }}>
        <p>Cannot reach server — check your connection.</p>
        <button style={{ padding: 8 }} onClick={hydrate}>Retry</button>
      </div>
    );
  if (user === undefined) return <p style={{ margin: "15vh auto", width: "fit-content" }}>Loading…</p>;
  if (!user) return <Login onLogin={setUser} />;
  if (!user.otp_enrolled) return <Enroll onDone={() => setUser({ ...user, otp_enrolled: true })} />;
  return <DemoPanel user={user} />;
}

function Login({ onLogin }) {
  const [form, setForm] = useState({ username: "", password: "", otp_code: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    const { status, data } = await api("auth/login/", form);
    setBusy(false);
    if (status === 200) onLogin({ ...data, authenticated: true });
    else setError(data.detail || "Login failed");
  }

  return (
    <form onSubmit={submit} style={{ maxWidth: 320, margin: "15vh auto", display: "grid", gap: 8 }}>
      <h2>Deploy Hub</h2>
      {["username", "password", "otp_code"].map((f) => (
        <input key={f} type={f === "password" ? "password" : "text"} style={box}
          aria-label={f === "otp_code" ? "TOTP or recovery code" : f}
          placeholder={f === "otp_code" ? "TOTP or recovery code (if enrolled)" : f}
          value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
      ))}
      <button style={{ padding: 8 }} disabled={busy}>{busy ? "Signing in…" : "Log in"}</button>
      {error && <div style={{ color: "#ff7b72" }}>{error}</div>}
    </form>
  );
}

function Enroll({ onDone }) {
  const [qr, setQr] = useState(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  // The codes are shown exactly once — losing the tab before saving them must
  // not be silent (round-1 UX finding).
  useEffect(() => {
    if (!recovery) return;
    const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [recovery]);

  async function start() {
    const { status, data } = await api("auth/totp/enroll/", {});
    if (status === 201) setQr(data);
    else setError(data.detail || "Enrollment failed to start");
  }

  async function confirm(e) {
    e.preventDefault();
    const { status, data } = await api("auth/totp/confirm/", { otp_code: code });
    if (status === 200) setRecovery(data.recovery_codes);
    else setError(data.detail || "Code did not verify");
  }

  if (recovery)
    return (
      <div style={{ maxWidth: 420, margin: "10vh auto" }}>
        <h2>Recovery codes — shown once</h2>
        <p>Store these offline (password manager / paper). Each works exactly once.</p>
        <pre style={{ ...box, lineHeight: 1.8 }}>{recovery.join("\n")}</pre>
        <button style={{ padding: 8, marginRight: 8 }}
          onClick={() => navigator.clipboard.writeText(recovery.join("\n"))
            .then(() => setCopied("ok"), () => setCopied("failed"))}>
          {copied === "ok" ? "Copied ✔"
            : copied === "failed" ? "Copy failed — select the codes manually"
            : "Copy to clipboard"}
        </button>
        <button style={{ padding: 8 }} onClick={onDone}>I saved them — continue</button>
      </div>
    );

  return (
    <div style={{ maxWidth: 420, margin: "10vh auto" }}>
      <h2>Set up two-factor auth</h2>
      <p>2FA is mandatory on this panel. Scan with your authenticator, then confirm one code.</p>
      {!qr ? (
        <button style={{ padding: 8 }} onClick={start}>Start enrollment</button>
      ) : (
        <form onSubmit={confirm} style={{ display: "grid", gap: 8 }}>
          <div style={{ background: "#fff", padding: 12, width: "fit-content" }}
            dangerouslySetInnerHTML={{ __html: qr.qr_svg }} />
          <small style={{ wordBreak: "break-all", color: "#8b949e" }}>{qr.otpauth_url}</small>
          <input style={box} aria-label="6-digit code" placeholder="6-digit code" value={code}
            onChange={(e) => setCode(e.target.value)} />
          <button style={{ padding: 8 }}>Confirm</button>
        </form>
      )}
      {error && <div style={{ color: "#ff7b72" }}>{error}</div>}
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

function DemoPanel({ user }) {
  const { status, subscribe, unsubscribe } = useEvents();
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
      setLines([`— launching ${values.name}… waiting for first log line —`]);
      subscribe(
        data.topic,
        (event) => {
          if (event.__snapshot) {
            // §D7 repaint: snapshot data is the capped history [{seq, event}] — a
            // socket killed mid-stream recovers every line published while dead.
            return setLines(event.data.map((e) => e.event.line ?? "✔ done"));
          }
          if (event.__snapshot_failed)
            return setLines((p) => [...p, snapshotFailedLine(event.status)]);
          setLines((p) => [...p, event.line ?? "✔ done"]);
        },
        snapshotFn
      );
    }
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
    <div style={{ maxWidth: 720, margin: "5vh auto", padding: 16 }}>
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
      <form onSubmit={handleSubmit((v) => launch(v, false))}
        style={{ display: "flex", gap: 8, alignItems: "end" }}>
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
