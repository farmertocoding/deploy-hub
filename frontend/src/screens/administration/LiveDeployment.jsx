import React, { useEffect, useState } from "react";
import { api } from "../../api.js";
import { DEPLOY_STEP_NAMES } from "../Deploys.jsx";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { Timeline } from "../../ui/Timeline.jsx";
import { Status } from "../../ui/Status.jsx";
import { Button } from "../../ui/Button.jsx";
import { AsyncRegion } from "../../ui/AsyncRegion.jsx";
import { ConfirmAction } from "../../ui/ConfirmAction.jsx";
import { STEP_LABELS } from "./contract.js";

export function fillDeploySteps(deploy) {
  const byName = Object.fromEntries((deploy?.steps || []).map((s) => [s.name, s]));
  return DEPLOY_STEP_NAMES.map((name) => ({
    ...(byName[name] || { name, state: "pending" }),
    name,
    label: STEP_LABELS[name] || name,
    state: (byName[name]?.state || byName[name]?.status || "pending"),
  }));
}

function actionLabel(action) {
  if (action?.label) return action.label;
  const id = String(action?.id || "").split(".").at(-1);
  if (!id) return "Unavailable action";
  return id.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function CopyId({ value }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      onClick={() => {
        if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
          navigator.clipboard.writeText(String(value));
        }
        setCopied(true);
      }}
    >
      {copied ? "Copied ✓" : "Copy ID"}
    </Button>
  );
}

export function LiveDeploymentView({
  deploy,
  phase = "live",
  error,
  onRetry,
  onNav,
  onCommand,
  pending,
  onCancelPending,
  drawer,
  onDrawer,
  commandResult,
}) {
  if (phase !== "live" && phase !== "degraded") {
    return <AsyncRegion phase={phase} what="deployment" error={error} onRetry={onRetry} />;
  }
  if (!deploy) {
    return <p>No deployment selected.</p>;
  }
  const steps = fillDeploySteps(deploy);
  const allowed = deploy.allowed_actions || [];
  const disabled = deploy.disabled_actions || [];
  const hasDelete = [...allowed, ...disabled].some((a) => /delete/i.test(a.id) || /delete/i.test(a.label || ""));
  const watching = [...allowed, ...disabled].some((a) => /keep watching/i.test(a.label || ""));
  const recoveryIds = new Set(["deployment.cancel", "deployment.abort", "deployment.retry", "deployment.rollback"]);
  const recovery = allowed.filter((a) => recoveryIds.has(a.id));
  const extraIds = new Set([
    "deployment.view_log", "deployment.view_artifacts",
    "site.view_health", "deployment.view_audit", "site.open_live",
  ]);
  const extras = allowed.filter((a) => extraIds.has(a.id));
  return (
    <div style={{ maxWidth: "100%" }}>
      <h1 className="hud-title">Live deployment</h1>
      <HudFrame variant="critical">
        <p role={deploy.state === "failed" ? "alert" : "status"}>{deploy.headline}</p>
        <p>
          <Status state={deploy.state} /> {deploy.site} v{deploy.version}
        </p>
        <p>Serving {deploy.live_release || "unknown"} — desired {deploy.desired_release}</p>
        <p>Rollback target: {deploy.previous_release || "none named"}</p>
        {deploy.safe_next ? <p>Safe next: {deploy.safe_next} — {deploy.safe_next_reason}</p> : null}
      </HudFrame>
      <div className="hud-grid-2" style={{ marginTop: 16 }}>
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Lifecycle</h2>
          <Timeline steps={steps} />
        </HudFrame>
        <HudFrame variant="panel">
          <h2 className="hud-kicker">Next action</h2>
          <div className="hud-actions">
          {commandResult ? (
            <p role="status">
              {commandResult.outcome}
              {commandResult.operation_id != null ? ` operation ${commandResult.operation_id}` : ""}
              {commandResult.state ? ` ${commandResult.state}` : ""}
              {commandResult.detail ? ` — ${commandResult.detail}` : ""}
            </p>
          ) : null}
          {pending ? (
            <ConfirmAction
              label={pending.label}
              summary={pending.summary}
              action={pending.id}
              objectId={deploy.id}
              current={deploy.state}
              proposed={pending.id}
              affected={[{ name: deploy.site }]}
              interruption={pending.id.includes("abort") ? "Running instance may stop." : "No interruption expected."}
              rollback={deploy.previous_release || "not named"}
              onConfirm={() => onCommand?.(pending)}
              onDismiss={onCancelPending}
            />
          ) : recovery.map((a) => (
            <Button
              key={a.id}
              variant={a.id.includes("abort") ? "destructive" : "primary"}
              onClick={() => onCommand?.({ ...a, summary: `${a.label} ${deploy.site} v${deploy.version}` })}
            >
              {a.label}
            </Button>
          ))}
          {disabled.filter((a) => a.id !== "deployment.delete").map((a) => (
            <Button key={a.id} disabled disabledReason={a.reason}>{actionLabel(a)}</Button>
          ))}
          <CopyId value={deploy.id} />
          {extras.filter((a) => a.id !== "deployment.copy").map((a) => (
            <Button
              key={a.id}
              variant="navigation"
              onClick={() => {
                if (a.id === "site.view_health") onNav("admin", `sites/${deploy.site_id || ""}`);
                else if (a.id === "deployment.view_audit") onNav("admin", `audit?object=deployment:${deploy.id}`);
                else if (a.id === "site.open_live") {
                  if (deploy.domain) window.open(`https://${deploy.domain}`, "_blank", "noopener");
                } else {
                  onDrawer?.(a.id);
                }
              }}
            >
              {a.label}
            </Button>
          ))}
          {hasDelete ? <p>Unexpected delete action</p> : null}
          {watching ? <p>Unexpected keep watching control</p> : null}
          </div>
        </HudFrame>
      </div>
      {drawer ? (
        <HudFrame variant="panel">
          <h2 className="hud-kicker">{drawer === "deployment.view_log" ? "Live log" : "Artifacts"}</h2>
          <pre className="hud-log">
            {drawer === "deployment.view_log"
              ? (deploy.log_text || "Streaming log for the current step.")
              : JSON.stringify(deploy.artifacts || { format: "json", kind: "step-artifacts" }, null, 2)}
          </pre>
          <Button onClick={() => onDrawer?.(null)}>Close</Button>
        </HudFrame>
      ) : null}
    </div>
  );
}

export default function LiveDeployment({ route, onNav, events }) {
  const id = (route?.id || "").split("/")[1];
  const [deploy, setDeploy] = useState(null);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(null);
  const [drawer, setDrawer] = useState(null);
  const [commandResult, setCommandResult] = useState(null);
  const applyDeploy = ({ status, data }) => {
    if (status === 401) { setPhase("signed-out"); return; }
    if (status === 403) { setPhase("permission-denied"); return; }
    if (status === 404) { setPhase("not-found"); return; }
    if (status !== 200) { setPhase("error"); setError(data?.detail || `HTTP ${status}`); return; }
    setDeploy(data);
    setPhase(events?.status === "degraded" ? "degraded" : "live");
  };
  const load = () => {
    if (!id) { setPhase("live"); return Promise.resolve(); }
    return api(`v1/hud/deployments/${id}/`).then(applyDeploy);
  };
  const subscribe = events?.subscribe;
  const unsubscribe = events?.unsubscribe;
  useEffect(() => {
    let cancelled = false;
    if (!id) { setPhase("live"); return undefined; }
    api(`v1/hud/deployments/${id}/`).then((result) => {
      if (!cancelled) applyDeploy(result);
    });
    return () => { cancelled = true; };
  }, [id, events?.status]);
  useEffect(() => {
    if (!id || !subscribe) return undefined;
    const topic = `deploy.${id}`;
    subscribe(topic, () => { load(); }, () => (
      api(`v1/hud/deployments/${id}/`).then(({ data }) => ({ seq: 0, data }))
    ));
    return () => { unsubscribe?.(topic); };
  }, [id, subscribe, unsubscribe]);
  return (
    <LiveDeploymentView
      deploy={deploy}
      phase={id ? phase : "live"}
      error={error}
      onNav={onNav}
      pending={pending}
      drawer={drawer}
      onDrawer={setDrawer}
      commandResult={commandResult}
      onRetry={load}
      onCancelPending={() => setPending(null)}
      onCommand={async (action) => {
        if (action.id === "site.view_health") {
          onNav("admin", "sites");
          return;
        }
        if (!pending) { setPending(action); return; }
        const { status, data } = await api(
          `v1/hud/deployments/${id}/commands/`,
          { action: action.id },
        );
        if (status === 202) {
          setCommandResult({
            outcome: "accepted",
            operation_id: data?.operation_id,
            state: data?.state,
            detail: data?.detail,
          });
          await load();
        } else if (status === 400 || status === 403 || status === 409) {
          setCommandResult({
            outcome: "refused",
            detail: data?.detail || `HTTP ${status}`,
          });
        } else {
          setCommandResult({
            outcome: "failed",
            detail: data?.detail || `HTTP ${status}`,
          });
        }
        setPending(null);
      }}
    />
  );
}
