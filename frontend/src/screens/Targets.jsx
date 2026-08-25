// Targets (§F1): the machines the Hub deploys to. Empty state is one sentence
// + one button: provision CLI when AWS_CREDENTIALS_REF is empty, else Create
// target (T1). Copy says Target, never "instance".
import React, { useEffect, useState } from "react";
import { EmptyState, ErrorLine, LoadingLine, routeHash } from "../Chrome.jsx";
import { ActionButton } from "../Tiers.jsx";
import { tierFor } from "../actions.js";
import { api } from "../api.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export const TARGET_TABS = [
  { id: "hardening", label: "Hardening" },
  { id: "router", label: "Router" },
];

export async function probeRouter(id) {
  return api(`v1/targets/${id}/router-probe/`, {});
}

export async function probeAndRefresh(id) {
  const probed = await probeRouter(id);
  if (probed.status < 200 || probed.status >= 300) return probed;
  const detail = await api(`v1/targets/${id}/`);
  if (detail.status !== 200) return probed;
  return { status: probed.status, data: detail.data };
}

export function adviceStatus(advice) {
  if (!advice) return { icon: "ℹ", label: "no advice" };
  if (advice.mode === "not_tunnel") return { icon: "ℹ", label: "not tunnel mode" };
  if (advice.mode === "no_seam") return { icon: "⚠", label: "no probe seam" };
  if (advice.forwarded) return { icon: "⚠", label: "forwarded" };
  return { icon: "✓", label: "nothing forwarded" };
}

export function RouterAdvice({ advice }) {
  if (!advice) return null;
  const status = adviceStatus(advice);
  return (
    <div>
      <p>{status.icon} {status.label}</p>
      {advice.title ? <p>{advice.title}</p> : null}
      {advice.body ? <p>{advice.body}</p> : null}
      {advice.finding_id ? (
        <a href={routeHash("findings", advice.finding_id)}
          style={{ color: "#79c0ff" }}>View finding</a>
      ) : null}
    </div>
  );
}

export function TargetDetail({ target, tab = "hardening", onTab, onProbe }) {
  return (
    <div style={{ ...box, marginTop: 12 }}>
      <nav style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        {TARGET_TABS.map((row) => (
          <button key={row.id} style={{ ...box, opacity: tab === row.id ? 1 : 0.6 }}
            onClick={() => onTab?.(row.id)}>{row.label}</button>
        ))}
      </nav>
      {tab === "hardening" && (
        <div data-tab="hardening">
          <p>Hardening findings stay in the Findings inbox. This tab does
            not invent a hardening engine.</p>
        </div>
      )}
      {tab === "router" && (
        <div data-tab="router">
          <RouterAdvice advice={target?.router_advice} />
          <ActionButton row={tierFor("target.router_probe")}
            onRun={() => (onProbe || probeAndRefresh)(target.id)} />
        </div>
      )}
    </div>
  );
}

export const PROVISION_CMD = "python -m hub provision <host>";

export async function deleteTarget(id, confirmName) {
  return api(`v1/targets/${id}/delete/`, { confirm_name: confirmName });
}

export async function createTarget(host, confirmName, extra = {}) {
  return api("v1/instance/create/", {
    host,
    confirm_name: confirmName,
    zone: extra.zone,
    instance_type: extra.instance_type,
  });
}

export async function instanceCreateCost() {
  return api("v1/instance/create/");
}

export const TARGET_CREATE_FAILED = "Target create failed";

export async function runCreateTarget(createFn, host, extra = {}) {
  const { status, data } = await createFn(host, host, extra);
  if (status < 200 || status >= 300) {
    return { ok: false, text: TARGET_CREATE_FAILED, status, data };
  }
  return { ok: true, host, status, data };
}

export function costFromCreateGet(status, data) {
  if (status === 200 && data?.cost_display) return data.cost_display;
  return null;
}

export function TargetsView({
  phase, targets = [], awsCredentialsRef = "", cost, onError, onCopy, onCreate,
  onRetryCost, selectedId, selected, tab = "hardening", onTab, onSelect,
  onProbe,
}) {
  if (phase === "loading") return <LoadingLine what="targets" />;
  if (phase === "error") return <ErrorLine text={onError.text} onRetry={onError.retry} />;
  if (!targets.length) {
    if (!awsCredentialsRef) {
      return <EmptyState
        sentence="No targets enrolled — provision a machine and it appears here."
        button="Copy the provision command" onAction={onCopy} />;
    }
    if (cost == null || cost === "") {
      return <EmptyState
        sentence="No targets enrolled — hourly cost is not available."
        button="Retry cost" onAction={onRetryCost} />;
    }
    return (
      <div style={{ margin: "10vh auto", width: "fit-content", textAlign: "center" }}>
        <p>No targets enrolled — create a target and it appears here.</p>
        <ActionButton row={tierFor("instance.create")} cost={cost}
          onRun={(args) => onCreate?.(args?.name)} />
      </div>
    );
  }
  const detail = selected && String(selected.id) === String(selectedId)
    ? selected
    : targets.find((t) => String(t.id) === String(selectedId));
  return (
    <div style={{ padding: 16 }}>
      {targets.map((t) => (
        <div key={t.id} style={{ display: "flex", gap: 8, alignItems: "center",
          marginBottom: 8, cursor: "pointer" }}
          role="button" tabIndex={0}
          onClick={() => onSelect?.(t.id)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect?.(t.id);
            }
          }}>
          <span>{t.host || t.name}</span>
          <span onClick={(e) => e.stopPropagation()}>
            <ActionButton row={tierFor("target.delete")} confirmName={t.host}
              onRun={() => deleteTarget(t.id, t.host)} />
          </span>
        </div>
      ))}
      {detail && (
        <TargetDetail target={detail} tab={tab} onTab={onTab} onProbe={onProbe} />
      )}
    </div>
  );
}

export default function Targets({ route, onNav }) {
  const [copied, setCopied] = useState(false);
  const [awsRef, setAwsRef] = useState("");
  const [cost, setCost] = useState(null);
  const [phase, setPhase] = useState("live");
  const [errorText, setErrorText] = useState("");
  const [createdHost, setCreatedHost] = useState("");
  const [targets, setTargets] = useState([]);
  const [selected, setSelected] = useState(null);
  const [tab, setTab] = useState("hardening");
  useEffect(() => {
    api("v1/aws/connect/").then(({ data }) => {
      const reason = data?.reason || "";
      if (!data?.connected && /HUB_AWS_CREDENTIALS_REF/.test(reason)) setAwsRef("");
      else if (data?.connected || reason) setAwsRef("set");
    });
    instanceCreateCost().then(({ status, data }) => {
      setCost(costFromCreateGet(status, data));
    });
    api("v1/targets/").then(({ status, data }) => {
      if (status === 200 && Array.isArray(data)) setTargets(data);
    });
  }, []);
  useEffect(() => {
    if (!route?.id) {
      setSelected(null);
      return;
    }
    const requested = route.id;
    setSelected(null);
    api(`v1/targets/${requested}/`).then(({ status, data }) => {
      if (status === 200 && String(data.id) === String(requested)
        && data.router_advice) setSelected(data);
    });
  }, [route?.id]);
  async function onProbe(id) {
    const result = await probeAndRefresh(id);
    if (result.status === 201 && result.data?.router_advice
      && String(result.data.id) === String(id)) setSelected(result.data);
    return result;
  }
  async function onCreate(host) {
    const result = await runCreateTarget(createTarget, host, { zone: "aws-use1" });
    if (!result.ok) {
      setPhase("error");
      setErrorText(TARGET_CREATE_FAILED);
      return;
    }
    setCreatedHost(host);
    api("v1/targets/").then(({ status, data }) => {
      if (status === 200 && Array.isArray(data)) setTargets(data);
    });
  }
  if (phase === "error") {
    return (
      <TargetsView phase="error"
        onError={{ text: errorText, retry: () => { setPhase("live"); setErrorText(""); } }} />
    );
  }
  return (
    <div>
      <TargetsView phase="live" targets={targets} awsCredentialsRef={awsRef} cost={cost}
        selectedId={route?.id} selected={selected} tab={tab} onTab={setTab}
        onSelect={(id) => onNav("targets", id)} onProbe={onProbe}
        onCreate={onCreate}
        onRetryCost={() => instanceCreateCost().then(({ status, data }) => {
          setCost(costFromCreateGet(status, data));
        })}
        onCopy={() => navigator.clipboard.writeText(PROVISION_CMD)
          .then(() => setCopied("ok"), () => setCopied("failed"))} />
      {createdHost && (
        <p style={{ textAlign: "center" }}>created {createdHost}</p>
      )}
      {copied === "ok" && (
        <p style={{ textAlign: "center", color: "#3fb950" }}>
          Copied ✔ — <code>{PROVISION_CMD}</code></p>
      )}
      {copied === "failed" && (
        <p style={{ textAlign: "center", color: "#e3b341" }}>
          Copy failed — run <code>{PROVISION_CMD}</code> yourself.</p>
      )}
    </div>
  );
}
