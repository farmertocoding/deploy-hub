// Deploys (§F1): deployment history and the live deploy status — §F6's third
// phone-width screen. No deploys endpoint exists yet (Tasks 4/13), so the screen's
// live state is its designed empty state, and DeployStatus is the CONTRACT Task 13
// wires the real payload into: single column, no fixed widths, the step list and the
// impact-shaped headline first (UX-F4 copy itself lands with the deploy payload).
import React from "react";
import { EmptyState, ErrorLine, LoadingLine } from "../Chrome.jsx";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

// The nine §D2 names, in seq order. A payload may send a subset; the stepper
// still draws every step so a failure at N is visible against the rest.
export const DEPLOY_STEP_NAMES = [
  "build", "ship", "migrate", "start_green", "health_check",
  "dns", "route_tls", "smoke_test", "cutover",
];

// deploy = { site, version, state, headline, steps, actions } — headline is
// the §F4 impact line from deploys/failure_impact.py (the one table).
export function DeployStatus({ deploy }) {
  const byName = Object.fromEntries((deploy.steps || []).map((s) => [s.name, s]));
  const steps = DEPLOY_STEP_NAMES.map((name) => byName[name] || { name, state: "pending" });
  const failed = deploy.state === "failed"
    || steps.some((s) => (s.state || s.status) === "failed");
  const impact = deploy.headline || deploy.impact;
  const actions = (deploy.actions || []).slice(0, 3);
  return (
    <div style={{ ...box, marginTop: 8, maxWidth: "100%", display: "grid", gap: 8 }}>
      <h3 style={{ margin: 0 }}>{deploy.site} — v{deploy.version}</h3>
      {failed && impact && <p role="alert" style={{ margin: 0 }}>{impact}</p>}
      {!failed && deploy.headline && <p style={{ margin: 0 }}>{deploy.headline}</p>}
      <div style={{ color: "#8b949e" }}>{deploy.state}</div>
      <ol style={{ margin: 0, paddingLeft: "1.4em" }}>
        {steps.map((s) => (
          <li key={s.name}>{s.name} — {s.state || s.status}</li>
        ))}
      </ol>
      {failed && actions.map((a) => (
        <button key={a.id} style={box}>{a.label} — {a.does}</button>
      ))}
    </div>
  );
}

export function DeploysView({ phase, deploys = [], onError, onNav }) {
  if (phase === "loading") return <LoadingLine what="deploys" />;
  if (phase === "error") return <ErrorLine text={onError.text} onRetry={onError.retry} />;
  if (!deploys.length)
    return <EmptyState
      sentence="No deployments yet — materialize a manifest on Home, then deploy it from its site."
      button="Open Sites" onAction={() => onNav("sites")} />;
  return (
    <div style={{ padding: 16 }}>
      {deploys.map((d) => <DeployStatus key={d.id} deploy={d} />)}
    </div>
  );
}

export default function Deploys({ onNav }) {
  return <DeploysView phase="live" deploys={[]} onNav={onNav} />;
}
