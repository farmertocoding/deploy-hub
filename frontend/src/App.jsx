// Phase 0 UI: login (password + TOTP) + demo log panel on the multiplexed socket.
// shadcn/ui + Tailwind (§A8) arrive with the first real screen; this stays plain
// so the demo proves plumbing, not styling.
import React, { useState } from "react";
import { useEvents } from "./useEvents.js";

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return m ? m[2] : "";
}

async function api(path, body) {
  const res = await fetch(`/api/${path}`, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

export default function App() {
  const [user, setUser] = useState(null);
  return user ? <DemoPanel user={user} /> : <Login onLogin={setUser} />;
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
        <input
          key={f}
          type={f === "password" ? "password" : "text"}
          placeholder={f === "otp_code" ? "TOTP code (if enrolled)" : f}
          value={form[f]}
          onChange={(e) => setForm({ ...form, [f]: e.target.value })}
          style={{ padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" }}
        />
      ))}
      <button style={{ padding: 8 }}>Log in</button>
      {error && <div style={{ color: "#ff7b72" }}>{error}</div>}
    </form>
  );
}

function DemoPanel({ user }) {
  const { status, subscribe } = useEvents();
  const [lines, setLines] = useState([]);
  const [name, setName] = useState("demo");
  const [problem, setProblem] = useState(null);

  async function launch(confirm = false) {
    setProblem(null);
    const { status: st, data } = await api("demo-jobs/", {
      name,
      delay: 0.5,
      confirm_warnings: confirm,
    });
    if (st === 400) setProblem({ kind: "errors", body: data.errors });
    else if (st === 409) setProblem({ kind: "warnings", body: data.warnings });
    else if (st === 201) {
      setLines([]);
      subscribe(data.topic, (event) =>
        setLines((prev) => [...prev, event.__gap ? "⚠ gap — refetching snapshot" : event.line ?? "✔ done"])
      );
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "5vh auto", padding: 16 }}>
      <h2>
        Demo job{" "}
        <small style={{ color: status === "live" ? "#7ee787" : "#f0b72f" }}>({status})</small>
      </h2>
      <p>Signed in as {user.username}. {!user.otp_enrolled && "⚠ Enroll TOTP in /admin before real use."}</p>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={name} onChange={(e) => setName(e.target.value)}
          style={{ padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" }} />
        <button onClick={() => launch(false)} style={{ padding: 8 }}>Launch</button>
      </div>
      {problem?.kind === "errors" && (
        <pre style={{ color: "#ff7b72" }}>{JSON.stringify(problem.body, null, 2)}</pre>
      )}
      {problem?.kind === "warnings" && (
        <div style={{ color: "#f0b72f", marginTop: 8 }}>
          {problem.body.map((w) => <div key={w.code}>⚠ {w.message} {w.hint}</div>)}
          <button onClick={() => launch(true)} style={{ marginTop: 8 }}>I understand, continue</button>
        </div>
      )}
      <pre style={{ background: "#161a21", padding: 12, minHeight: 220, marginTop: 16 }}>
        {lines.join("\n")}
      </pre>
    </div>
  );
}
