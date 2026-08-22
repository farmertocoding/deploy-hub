// Deploys (§F1): deployment history and the live deploy status — §F6's third
// phone-width screen. No deploys endpoint exists yet (Tasks 4/13), so the screen's
// live state is its designed empty state, and DeployStatus is the CONTRACT Task 13
// wires the real payload into: single column, no fixed widths, the step list and the
// impact-shaped headline first (UX-F4 copy itself lands with the deploy payload).
import React from "react";
import { EmptyState, ErrorLine, LoadingLine } from "../Chrome.jsx";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

// deploy = { site, version, state, headline, steps: [{name, state}] } — Task 13's
// serializer shape; typed here as the interface the phone-width pin renders against.
export function DeployStatus({ deploy }) {
  return (
    <div style={{ ...box, marginTop: 8, maxWidth: "100%", display: "grid", gap: 8 }}>
      <h3 style={{ margin: 0 }}>{deploy.site} — v{deploy.version}</h3>
      {deploy.headline && <p style={{ margin: 0 }}>{deploy.headline}</p>}
      <div style={{ color: "#8b949e" }}>{deploy.state}</div>
      <ol style={{ margin: 0, paddingLeft: "1.4em" }}>
        {(deploy.steps || []).map((s) => (
          <li key={s.name}>{s.name} — {s.state}</li>
        ))}
      </ol>
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
