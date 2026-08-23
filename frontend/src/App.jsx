// The operator shell (Task 12a): login (password + TOTP) → forced TOTP enrollment
// (§6.10 mandatory-2FA) → the §F1 object-centric nav. The Phase-0 demo pane lives on
// as a Settings/Developer tab (screens/Settings.jsx) — it proves plumbing, not the
// product surface. Still plain React + inline styles: shadcn/Tailwind (§A8) arrive
// with a styling pass, and mockup-first is the working agreement.
import React, { useEffect, useState } from "react";
import { useEvents } from "./useEvents.js";
import { api, simState } from "./api.js";
import ReadinessScreen from "./Readiness.jsx";
import { NAV, StatusPill, useRoute, useWidth } from "./Chrome.jsx";
import Home from "./screens/Home.jsx";
import Sites from "./screens/Sites.jsx";
import Targets from "./screens/Targets.jsx";
import Deploys from "./screens/Deploys.jsx";
import Findings from "./screens/Findings.jsx";
import Settings from "./screens/Settings.jsx";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export default function App() {
  // Hydrate the session on load: restores login state across reloads AND plants
  // the CSRF cookie the (CSRF-protected) login POST needs.
  const [user, setUser] = useState(undefined); // undefined = loading
  const [unreachable, setUnreachable] = useState(false);
  // §F8 simulation: ?sim=<state> reviews the readiness screen with no backend at
  // all, so auth (which needs a server) is skipped and the fixtures take over.
  if (simState()) return <ReadinessScreen />;
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
  return <Shell user={user} />;
}

// The nav bar, extracted so tests/nav.test.ts renders the IA without mounting the
// socket-owning Shell (renderToStaticMarkup runs no effects, but the pin belongs on
// markup a test can actually produce).
export function NavBar({ route, onNav, status, asOf, username }) {
  return (
    <nav style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: 8,
      alignItems: "center", borderBottom: "1px solid #333" }}>
      {NAV.map((n) => (
        <button key={n.id} style={{ ...box, opacity: route.screen === n.id ? 1 : 0.6 }}
          aria-current={route.screen === n.id ? "page" : undefined}
          onClick={() => onNav(n.id)}>{n.label}</button>
      ))}
      <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
        <StatusPill status={status} asOf={asOf} />
        <span style={{ color: "#8b949e" }}>{username}</span>
      </span>
    </nav>
  );
}

function Shell({ user }) {
  // ONE multiplexed socket for the whole shell (§3.5): screens subscribe through
  // this client, and the pill beside the username is RT-35's visible state — every
  // screen shows it because it is above all of them.
  const events = useEvents();
  const [route, onNav] = useRoute();
  const width = useWidth();
  return (
    <div>
      <NavBar route={route} onNav={onNav} status={events.status} asOf={events.asOf}
        username={user.username} />
      {route.screen === "home" && <Home width={width} events={events} onNav={onNav} />}
      {route.screen === "sites" && <Sites route={route} onNav={onNav} />}
      {route.screen === "targets" && <Targets />}
      {route.screen === "deploys" && <Deploys onNav={onNav} />}
      {route.screen === "findings" && <Findings route={route} onNav={onNav} events={events} />}
      {route.screen === "settings" && <Settings user={user} events={events} />}
    </div>
  );
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
