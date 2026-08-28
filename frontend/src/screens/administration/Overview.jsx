import React, { useEffect, useState } from "react";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { Status } from "../../ui/Status.jsx";
import { Chart } from "../../ui/Chart.jsx";
import { AsyncRegion } from "../../ui/AsyncRegion.jsx";
import { Button } from "../../ui/Button.jsx";
import { adminHref, currentScope, hudGet, scopedCount } from "./contract.js";

export async function overviewSnapshot(route) {
  return hudGet("v1/hud/overview/", route);
}

export function OverviewView({ data, onNav, asOf, phase = "live", error, onRetry }) {
  if (phase !== "live" && phase !== "degraded") {
    return <AsyncRegion phase={phase} what="overview" error={error} onRetry={onRetry} asOf={asOf} />;
  }
  const findings = data?.findings || {};
  const deploys = data?.deployments || {};
  const health = data?.site_health || {};
  const targets = data?.target_readiness || {};
  const p1p2 = (findings.p1 || 0) + (findings.p2 || 0);
  const allowed = data?.allowed_actions || [];
  const canCreate = allowed.find((a) => a.id === "project.create");
  const setup = data?.setup || [];
  const metrics = [
    {
      id: "p1",
      kicker: "Attention required",
      value: scopedCount(p1p2, "P1/P2"),
      href: "findings",
      hrefQuery: { facet: "p1p2" },
      drill: "View attention queue",
    },
    {
      id: "deploys",
      kicker: "Deployments",
      value: `${scopedCount(deploys.queued || 0, "queued")} · ${scopedCount(deploys.running || 0, "running")} · ${scopedCount(deploys.waiting_for_lock || 0, "waiting-for-lock")}`,
      href: "deployments",
      hrefQuery: { facet: "active" },
      drill: "View deployments",
    },
    {
      id: "sites",
      kicker: "Sites",
      value: scopedCount(health.healthy || 0, "healthy sites"),
      href: "sites",
      drill: "View sites",
    },
    {
      id: "targets",
      kicker: "Targets",
      value: scopedCount(targets.ready || 0, "ready targets"),
      href: "targets",
      drill: "View targets",
    },
  ];
  const activity = (data?.activity || data?.active_deployments || []).map((d) => ({
    label: d.site || d.label,
    value: d.value ?? 1,
  }));
  return (
    <AsyncRegion phase={phase} asOf={asOf || data?.observed_at} what="overview">
      <div className="hud-toolbar" data-fetched-scope={data?.scope || ""}>
        <h1 className="hud-title">Fleet overview</h1>
        {canCreate ? (
          <Button variant="primary" onClick={() => onNav("admin", "projects/new")}>
            ADD APPLICATION
          </Button>
        ) : null}
      </div>
      <p className="hud-kicker">Workspace counts — none of these cards mutate fleet state</p>
      <div className="hud-metrics">
        {metrics.map((m) => (
          <HudFrame key={m.id} variant="compact">
            <p className="hud-kicker">{m.kicker}</p>
            <p className="hud-metric">{m.value}</p>
            <Button variant="navigation" onClick={() => onNav("admin", adminHref(m.href, m.hrefQuery))}>
              {m.drill}
            </Button>
          </HudFrame>
        ))}
      </div>
      <div className="hud-grid-2" style={{ marginTop: 16 }}>
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Attention queue</h2>
          {(data?.attention || []).length === 0 ? (
            <p>No open attention items — the queue is clear.</p>
          ) : (
            <ul>
              {(data.attention || []).map((item) => (
                <li key={item.id}>
                  <Status state={item.severity} /> {item.title}{" "}
                  <Button variant="navigation" onClick={() => onNav("admin", `findings/${item.id.replace(/^finding-/, "")}`)}>
                    REVIEW
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </HudFrame>
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Active deployments</h2>
          {(data?.active_deployments || []).map((d) => (
            <p key={d.id}>
              <button type="button" className="hud-btn hud-btn--quiet" onClick={() => onNav("admin", `deployments/${d.id}`)}>
                <Status state={d.state} /> {d.site} v{d.version} — {d.current_step}
              </button>
            </p>
          ))}
          <Chart
            title="Deployment activity"
            range="current window"
            points={activity.length ? activity : [{ label: "none", value: 0 }]}
          />
        </HudFrame>
      </div>
      <div className="hud-grid-2" style={{ marginTop: 16 }}>
        <HudFrame variant="compact">
          <h2 className="hud-kicker">Integrations</h2>
          <p>AWS — {data?.integrations?.aws || "unknown"}</p>
          <p>Cloudflare — {data?.integrations?.cloudflare || "unknown"}</p>
          <p>Vault — {data?.integrations?.vault || "unknown"}</p>
          <p>Notifications — {data?.integrations?.notifications || "unknown"}</p>
          <Button variant="navigation" onClick={() => onNav("admin", "integrations")}>
            View integrations
          </Button>
        </HudFrame>
        <HudFrame variant="compact">
          <h2 className="hud-kicker">Fleet health</h2>
          <p>{scopedCount(health.healthy || 0, "healthy")}</p>
          <p>{scopedCount(health.warming || 0, "warming")}</p>
          <p>{scopedCount(health.unhealthy || 0, "unhealthy")}</p>
          <p>{scopedCount(health.stale || 0, "stale")}</p>
          <Button variant="navigation" onClick={() => onNav("admin", "sites")}>
            View fleet health
          </Button>
        </HudFrame>
      </div>
      {setup.length ? (
        <HudFrame variant="compact">
          <h2 className="hud-kicker">First-run checklist</h2>
          {setup.map((s) => <p key={s.id}>{s.title}</p>)}
          <Button variant="primary" onClick={() => onNav("admin", setup[0].href || "targets")}>
            FINISH SETUP
          </Button>
        </HudFrame>
      ) : null}
    </AsyncRegion>
  );
}

export default function Overview({ onNav, events, route }) {
  const [phase, setPhase] = useState("loading");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const scope = currentScope(route);
  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    overviewSnapshot(route).then((body) => {
      if (!cancelled) { setData(body); setPhase("live"); }
    }).catch((err) => {
      if (!cancelled) {
        setError(err?.data?.detail || "HTTP error");
        setPhase(err.denied ? "permission-denied" : err.signedOut ? "signed-out" : "error");
      }
    });
    return () => { cancelled = true; };
  }, [events, scope, tick]);
  return (
    <OverviewView
      data={data}
      onNav={onNav}
      phase={phase}
      error={error}
      asOf={events?.asOf || data?.observed_at}
      onRetry={() => setTick((n) => n + 1)}
    />
  );
}
