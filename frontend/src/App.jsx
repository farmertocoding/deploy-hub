// Phase 0 UI: login (password + TOTP) → forced TOTP enrollment (§6.10 mandatory-2FA)
// → demo log panel on the multiplexed socket. shadcn/Tailwind (§A8) arrive with the
// first real screen; this stays plain so the demo proves plumbing, not styling.
import React, { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { schemas } from "./api/zod.ts";
import { useEvents } from "./useEvents.js";

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return m ? m[2] : "";
}

async function api(path, body) {
  const res = await fetch(`/api/${path}`, {
    method: body !== undefined ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export default function App() {
  const [user, setUser] = useState(null);
  if (!user) return <Login onLogin={setUser} />;
  if (!user.otp_enrolled) return <Enroll onDone={() => setUser({ ...user, otp_enrolled: true })} />;
  return <DemoPanel user={user} />;
}

function Login({ onLogin }) {
  const [form, setForm] = useState({ username: "", password: "", otp_code: "" });
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    const { status, data } = await api("auth/login/", form);
    if (status === 200) onLogin(data);
    else setError(data.detail || "Login failed");
  }

  return (
    <form onSubmit={submit} style={{ maxWidth: 320, margin: "15vh auto", display: "grid", gap: 8 }}>
      <h2>Deploy Hub</h2>
      {["username", "password", "otp_code"].map((f) => (
        <input key={f} type={f === "password" ? "password" : "text"} style={box}
          placeholder={f === "otp_code" ? "TOTP or recovery code (if enrolled)" : f}
          value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
      ))}
      <button style={{ padding: 8 }}>Log in</button>
      {error && <div style={{ color: "#ff7b72" }}>{error}</div>}
    </form>
  );
}

function Enroll({ onDone }) {
  const [qr, setQr] = useState(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(null);
  const [error, setError] = useState("");

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
          <input style={box} placeholder="6-digit code" value={code}
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

function DemoPanel({ user }) {
  const { status, subscribe } = useEvents();
  const [lines, setLines] = useState([]);
  const [warnings, setWarnings] = useState(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(schemas.DemoJob, { errorMap: demoJobErrorMap }),
    defaultValues: { name: "demo", delay: 0.5, confirm_warnings: false },
  });

  async function launch(values, confirm = false) {
    setWarnings(null);
    const { status: st, data } = await api("demo-jobs/", {
      ...values, confirm_warnings: confirm,
    });
    if (st === 400) {
      // Server verdict wins (§4.5): map {field: [{code, message, hint}]} into RHF.
      for (const [field, errs] of Object.entries(data.errors ?? {})) {
        const e = errs[0];
        setError(field, { type: e.code, message: [e.message, e.hint].filter(Boolean).join(" ") });
      }
    } else if (st === 409) setWarnings({ values, body: data.warnings });
    else if (st === 201) {
      setLines([]);
      subscribe(
        data.topic,
        (event) => {
          if (event.__snapshot) return; // demo topic has no history to replay
          if (event.__snapshot_failed) return setLines((p) => [...p, "⚠ snapshot refetch failed"]);
          setLines((p) => [...p, event.line ?? "✔ done"]);
        },
        // Snapshot-then-stream (§D7): same fetch on first load and on every reconnect.
        async (topic) => (await api(`topics/${topic}/snapshot/`)).data
      );
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "5vh auto", padding: 16 }}>
      <h2>
        Demo job{" "}
        <small style={{ color: status === "live" ? "#7ee787" : "#f0b72f" }}>({status})</small>
      </h2>
      <p>Signed in as {user.username}.</p>
      <form onSubmit={handleSubmit((v) => launch(v, false))}
        style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input {...register("name")} style={box} aria-invalid={!!errors.name} />
        <input {...register("delay", { valueAsNumber: true })} type="number" step="0.05"
          style={{ ...box, width: 80 }} aria-invalid={!!errors.delay} title="delay (s)" />
        <button style={{ padding: 8 }}>Launch</button>
      </form>
      {Object.entries(errors).map(([field, e]) => (
        <div key={field} style={{ color: "#ff7b72", marginTop: 8 }}>
          {field}: {e.message}
        </div>
      ))}
      {warnings && (
        <div style={{ color: "#f0b72f", marginTop: 8 }}>
          {warnings.body.map((w) => <div key={w.code}>⚠ {w.message} {w.hint}</div>)}
          <button onClick={() => launch(warnings.values, true)} style={{ marginTop: 8 }}>
            I understand, continue
          </button>
        </div>
      )}
      <pre style={{ background: "#161a21", padding: 12, minHeight: 220, marginTop: 16 }}>
        {lines.join("\n")}
      </pre>
    </div>
  );
}
