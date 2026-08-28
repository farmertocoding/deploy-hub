import React, { useEffect, useState } from "react";
import { api } from "../../api.js";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { AsyncRegion } from "../../ui/AsyncRegion.jsx";
import { Button } from "../../ui/Button.jsx";
import { Status } from "../../ui/Status.jsx";

const TABS = [
  "overview", "configuration", "environment", "releases",
  "instances", "backups", "adoption", "activity", "removal",
];

export function SiteDetailView({ data, tab = "overview", onTab, onNav, phase = "live", error, onRetry }) {
  if (phase !== "live" && phase !== "degraded") {
    return <AsyncRegion phase={phase} what="site" error={error} onRetry={onRetry} />;
  }
  if (!data) return <p>No site selected.</p>;
  return (
    <div>
      <h1 className="hud-title">{data.project}/{data.name}</h1>
      <div className="hud-facets" role="tablist" aria-label="Site detail">
        {TABS.map((id) => (
          <Button
            key={id}
            role="tab"
            aria-selected={tab === id}
            variant={tab === id ? "primary" : "quiet"}
            onClick={() => onTab?.(id)}
          >
            {id}
          </Button>
        ))}
      </div>
      <HudFrame variant="panel" role="tabpanel">
        {tab === "overview" ? (
          <div>
            <p><Status state={data.health} /> {data.domain}</p>
            <p>Environment {data.environment} · exposure {data.exposure}</p>
            <p>TLS {data.tls} · backup {data.backup}</p>
            <p>Live {data.live_release || "unknown"} → desired {data.desired_release || "unknown"}</p>
            <p>Owner {data.owner || "unknown"} · copies {data.copies ?? 0}</p>
            <p>Target {data.target || "none"}</p>
          </div>
        ) : null}
        {tab === "configuration" ? (
          <p>Strategy {data.deploy_strategy} · policy {data.deploy_policy} · window {data.deploy_window_cron || "none"}</p>
        ) : null}
        {tab === "environment" ? (
          <p>Environment and secrets stay write-only in Vault. This tab lists owners, not values.</p>
        ) : null}
        {tab === "releases" ? (
          <ul>{(data.manifests || []).map((m) => <li key={m.id}>v{m.version}</li>)}</ul>
        ) : null}
        {tab === "instances" ? (
          <ul>
            {(data.instances || []).map((i) => (
              <li key={i.id}>{i.target} — {i.observed_state}</li>
            ))}
          </ul>
        ) : null}
        {tab === "backups" ? <p>Backup {data.backup}</p> : null}
        {tab === "adoption" ? <p>Adoption remains an Operator Console workflow.</p> : null}
        {tab === "activity" ? (
          <p>Active deployment {data.active_deployment || "none"} · observed {data.observed_at}</p>
        ) : null}
        {tab === "removal" ? (
          <p>Decommission requires a dependency-aware plan. Delete is not offered here.</p>
        ) : null}
        <Button variant="navigation" onClick={() => onNav?.("admin", "sites")}>Back to fleet</Button>
      </HudFrame>
    </div>
  );
}

export default function SiteDetail({ route, onNav }) {
  const id = (route?.id || "").split("/")[1];
  const tab = route?.query?.tab || "overview";
  const [data, setData] = useState(null);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!id) return undefined;
    let cancelled = false;
    api(`v1/hud/sites/${id}/`).then(({ status, data: body }) => {
      if (cancelled) return;
      if (status !== 200) {
        setPhase(status === 403 ? "permission-denied" : status === 404 ? "not-found" : "error");
        setError(body?.detail || `HTTP ${status}`);
        return;
      }
      setData(body);
      setPhase("live");
    });
    return () => { cancelled = true; };
  }, [id]);
  return (
    <SiteDetailView
      data={data}
      tab={tab}
      onTab={(next) => onNav("admin", `sites/${id}?tab=${next}`)}
      onNav={onNav}
      phase={phase}
      error={error}
      onRetry={() => {
        setPhase("loading");
        api(`v1/hud/sites/${id}/`).then(({ status, data: body }) => {
          if (status === 200) { setData(body); setPhase("live"); }
          else { setPhase("error"); setError(body?.detail || `HTTP ${status}`); }
        });
      }}
    />
  );
}
