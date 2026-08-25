// The operator shell: login (WebAuthn primary, TOTP fallback) → forced passkey
// enrollment → the §F1 object-centric nav. ?sim= mounts Shell (C9); login/enroll/t1
// are named sim states so F8 can see them without a backend.
import React, { useEffect, useState } from "react";
import { useEvents } from "./useEvents.js";
import { api, simState } from "./api.js";
import { NAV, StatusPill, useRoute, useWidth } from "./Chrome.jsx";
import Home from "./screens/Home.jsx";
import Sites from "./screens/Sites.jsx";
import Targets from "./screens/Targets.jsx";
import Deploys from "./screens/Deploys.jsx";
import Findings from "./screens/Findings.jsx";
import Settings from "./screens/Settings.jsx";
import Login from "./screens/Login.jsx";
import Enroll from "./screens/Enroll.jsx";
import { T1Overlay } from "./Tiers.jsx";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export { Login, Enroll };

export default function App() {
  const sim = simState();
  if (sim === "login") return <Login onLogin={() => {}} />;
  if (sim === "enroll") return <Enroll onDone={() => {}} />;
  if (sim === "t1")
    return (
      <div style={{ maxWidth: "100%", width: 390, margin: "8px auto" }}>
        <T1Overlay label="Delete target" onTouch={() => {}} onConfirm={() => {}}
          onDismiss={() => {}} />
      </div>
    );
  // Other ?sim= states skip auth and mount the operator chrome so Login/Enroll
  // are not the only reviewable surfaces — Home still owns readiness.
  if (sim)
    return <Shell user={{ username: "sim", otp_enrolled: true, webauthn_count: 2 }} />;

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

export function Shell({ user }) {
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
      {route.screen === "targets" && <Targets route={route} onNav={onNav} />}
      {route.screen === "deploys" && <Deploys onNav={onNav} />}
      {route.screen === "findings" && <Findings route={route} onNav={onNav} events={events} />}
      {route.screen === "settings" && <Settings user={user} events={events} />}
    </div>
  );
}


