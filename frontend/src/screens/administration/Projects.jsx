import React, { useEffect, useState } from "react";
import { CollectionScreen } from "./CollectionScreen.jsx";
import { Button } from "../../ui/Button.jsx";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { currentScope, hudGet, hudPost } from "./contract.js";
import { Status } from "../../ui/Status.jsx";
import { useHudActions } from "./useHudActions.js";

const STEPS = ["Source", "First Site", "Placement and policy", "Review"];

export function AddApplicationWizard({ onNav, onCreated }) {
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sourceStatus, setSourceStatus] = useState("");
  const [dirty, setDirty] = useState(false);
  const [form, setForm] = useState({
    name: "",
    git_url: "",
    git_ref: "main",
    local_path: "",
    site_name: "prod",
    environment: "production",
    exposure: "public",
    domain: "",
    proxied: true,
    dns_zone: "",
    primary_target: "",
    deploy_strategy: "blue_green",
    deploy_policy: "auto",
    deploy_window_cron: "",
  });
  const set = (key) => (event) => {
    setDirty(true);
    setForm((f) => ({ ...f, [key]: event.target.value }));
  };

  const sourceOk = sourceStatus === "connected" || sourceStatus === "unknown";
  const canContinue = step === 0
    ? Boolean(form.name && (form.git_url || form.local_path) && sourceOk)
    : step === 1
      ? Boolean(form.site_name && (form.exposure === "mesh_only" || form.domain))
      : step === 2
        ? Boolean(form.deploy_strategy && form.deploy_policy)
        : true;

  const testSource = async () => {
    setSourceStatus("checking");
    try {
      const q = form.local_path
        ? `local_path=${encodeURIComponent(form.local_path)}`
        : `git_url=${encodeURIComponent(form.git_url)}`;
      const data = await hudGet(`v1/hud/projects/test-source/?${q}`);
      setSourceStatus(data.state || (data.ok ? "connected" : "failed"));
    } catch (err) {
      setSourceStatus(err?.data?.detail || "failed");
    }
  };

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const { status, data } = await hudPost("v1/hud/projects/", {
        name: form.name,
        git_url: form.git_url,
        git_ref: form.git_ref,
        local_path: form.local_path,
        domain: form.domain,
        exposure: form.exposure,
        proxied: form.proxied,
        site_name: form.site_name,
        environment: form.environment,
        dns_zone: form.dns_zone ? Number(form.dns_zone) : undefined,
        primary_target: form.primary_target ? Number(form.primary_target) : undefined,
        deploy_strategy: form.deploy_strategy,
        deploy_policy: form.deploy_policy,
        deploy_window_cron: form.deploy_window_cron,
      });
      if (status === 201 || status === 202) {
        onCreated?.(data);
        onNav?.("admin", data.id ? `projects/${data.id}` : "projects");
        return;
      }
      setError(data?.detail || `Unexpected ${status}`);
    } catch (err) {
      setError(err?.data?.detail || "Create failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <HudFrame variant="panel">
      <h2 className="hud-kicker">Add application — {STEPS[step]}</h2>
      {step === 0 ? (
        <form className="hud-filter" onSubmit={(e) => e.preventDefault()}>
          <label>Project name<input aria-label="Project name" value={form.name} onChange={set("name")} /></label>
          <label>Git URL<input aria-label="Git URL" value={form.git_url} onChange={set("git_url")} /></label>
          <label>Git ref<input aria-label="Git ref" value={form.git_ref} onChange={set("git_ref")} /></label>
          <label>Local path<input aria-label="Local path" value={form.local_path} onChange={set("local_path")} /></label>
          <Button onClick={testSource}>Test source</Button>
          {sourceStatus ? <p>Connection status: {sourceStatus}</p> : null}
        </form>
      ) : null}
      {step === 1 ? (
        <form className="hud-filter" onSubmit={(e) => e.preventDefault()}>
          <label>Site name<input aria-label="Site name" value={form.site_name} onChange={set("site_name")} /></label>
          <label>Environment
            <select aria-label="Environment" value={form.environment} onChange={set("environment")}>
              <option value="production">production</option>
              <option value="staging">staging</option>
              <option value="preview">preview</option>
              <option value="development">development</option>
            </select>
          </label>
          <label>Exposure
            <select aria-label="Exposure" value={form.exposure} onChange={set("exposure")}>
              <option value="public">public</option>
              <option value="mesh_only">mesh_only</option>
            </select>
          </label>
          <label>Domain<input aria-label="Domain" value={form.domain} onChange={set("domain")} /></label>
        </form>
      ) : null}
      {step === 2 ? (
        <form className="hud-filter" onSubmit={(e) => e.preventDefault()}>
          <label>DNS zone id<input aria-label="DNS zone" value={form.dns_zone} onChange={set("dns_zone")} /></label>
          <label>Primary target id<input aria-label="Primary target" value={form.primary_target} onChange={set("primary_target")} /></label>
          <label>Strategy
            <select aria-label="Deploy strategy" value={form.deploy_strategy} onChange={set("deploy_strategy")}>
              <option value="blue_green">blue_green</option>
              <option value="recreate">recreate</option>
            </select>
          </label>
          <label>Policy
            <select aria-label="Deploy policy" value={form.deploy_policy} onChange={set("deploy_policy")}>
              <option value="auto">auto</option>
              <option value="confirm">confirm</option>
              <option value="windowed">windowed</option>
            </select>
          </label>
          <label>Window cron<input aria-label="Deploy window" value={form.deploy_window_cron} onChange={set("deploy_window_cron")} /></label>
        </form>
      ) : null}
      {step === 3 ? (
        <div>
          <p>This creates one Project and one Site. Nothing will be deployed.</p>
          <p>{form.name} → {form.domain || form.site_name} ({form.exposure})</p>
        </div>
      ) : null}
      {error ? <p className="hud-async__reason">{error}</p> : null}
      <div className="hud-toolbar">
        {step > 0 ? <Button onClick={() => setStep((s) => s - 1)}>Back</Button> : null}
        {step < 3 ? (
          <Button
            variant="primary"
            disabled={!canContinue}
            disabledReason={!canContinue ? "Complete this step before continuing." : undefined}
            onClick={() => { if (canContinue) setStep((s) => s + 1); }}
          >
            Continue
          </Button>
        ) : (
          <Button variant="primary" busy={busy} onClick={create}>Create application</Button>
        )}
        <Button onClick={() => {
          if (dirty && typeof window !== "undefined" && !window.confirm("Discard unsaved application draft?")) return;
          onNav?.("admin", "projects");
        }}>Cancel</Button>
      </div>
    </HudFrame>
  );
}

export function ProjectsView({
  rows = [],
  collectionActions = [],
  phase = "live",
  error,
  onRetry,
  asOf,
  deniedReason,
  selectedId,
  onSelect,
  onNav,
  pending,
  onConfirmPending,
  onCancelPending,
  actionHandlers = {},
  wizard,
  lastCommand,
}) {
  return (
    <CollectionScreen
      title="Projects"
      caption="Projects"
      columns={[
        { id: "name", label: "Name" },
        { id: "slug", label: "Slug" },
        { id: "source_kind", label: "Source" },
        { id: "source", label: "Git URL / path" },
        { id: "scan_state", label: "Scan" },
        { id: "sites", label: "Sites" },
        { id: "actions", label: "Actions" },
      ]}
      rows={rows}
      collectionActions={collectionActions.map((a) => ({
        ...a,
        primary: a.id === "project.create",
      }))}
      actionHandlers={actionHandlers}
      selectedId={selectedId}
      onSelect={onSelect}
      onNav={onNav}
      phase={phase}
      error={error}
      onRetry={onRetry}
      asOf={asOf}
      deniedReason={deniedReason}
      emptySentence="No projects in this workspace — add an application to start."
      emptyButton="ADD APPLICATION"
      onEmpty={() => onNav?.("admin", "projects/new")}
      pending={pending}
      onConfirmPending={onConfirmPending}
      onCancelPending={onCancelPending}
      inspector={selectedId ? {
        body: (() => {
          const row = rows.find((r) => String(r.id) === String(selectedId));
          if (!row) return <p>Select a project.</p>;
          return (
            <div>
              <p>{row.name} / {row.slug}</p>
              <p>Source {row.source_kind} {row.source}</p>
              <Status state={row.scan_state === "scanned" ? "healthy" : "pending"} />
              {lastCommand ? <p>Last command {lastCommand.body?.action} {lastCommand.result?.operation_id}</p> : null}
            </div>
          );
        })(),
      } : null}
      inspectorTitle="Project"
    >
      {wizard ? <AddApplicationWizard onNav={onNav} /> : null}
    </CollectionScreen>
  );
}

export default function Projects({ route, onNav, width }) {
  const [rows, setRows] = useState([]);
  const [actions, setActions] = useState([]);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [asOf, setAsOf] = useState(null);
  const [tick, setTick] = useState(0);
  const objectId = (route?.id || "").split("/")[1];
  const { pending, lastCommand, handlers, onCancelPending, onConfirmPending } = useHudActions({ onNav });
  const scope = currentScope(route);
  useEffect(() => {
    let cancelled = false;
    hudGet("v1/hud/projects/", route).then((body) => {
      if (cancelled) return;
      setRows(body.results || []);
      setActions(body.allowed_actions || [{ id: "project.create", label: "ADD APPLICATION" }]);
      setAsOf(body.observed_at);
      setPhase("live");
    }).catch((err) => {
      if (cancelled) return;
      setPhase(err.denied ? "permission-denied" : err.signedOut ? "signed-out" : "error");
      setError(err?.data?.detail || "HTTP error");
    });
    return () => { cancelled = true; };
  }, [scope, lastCommand, tick]);
  return (
    <ProjectsView
      rows={rows}
      collectionActions={actions}
      phase={phase}
      error={error}
      asOf={asOf}
      onRetry={() => setTick((n) => n + 1)}
      selectedId={objectId === "new" ? undefined : objectId}
      onSelect={(id) => onNav("admin", id ? `projects/${id}` : "projects")}
      onNav={onNav}
      wizard={objectId === "new"}
      actionHandlers={handlers}
      pending={pending}
      onCancelPending={onCancelPending}
      onConfirmPending={onConfirmPending}
      lastCommand={lastCommand}
      width={width}
    />
  );
}
