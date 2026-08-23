// Targets (§F1): the machines the Hub deploys to. Empty state is one sentence
// + one button: provision CLI when AWS_CREDENTIALS_REF is empty, else Create
// target (T1). Copy says Target, never "instance".
import React, { useEffect, useState } from "react";
import { EmptyState, ErrorLine, LoadingLine } from "../Chrome.jsx";
import { ActionButton } from "../Tiers.jsx";
import { tierFor } from "../actions.js";
import { api } from "../api.js";

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
  onRetryCost,
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
  return (
    <div style={{ padding: 16 }}>
      {targets.map((t) => (
        <div key={t.id} style={{ display: "flex", gap: 8, alignItems: "center",
          marginBottom: 8 }}>
          <span>{t.host || t.name}</span>
          <ActionButton row={tierFor("target.delete")} confirmName={t.host}
            onRun={() => deleteTarget(t.id, t.host)} />
        </div>
      ))}
    </div>
  );
}

export default function Targets() {
  const [copied, setCopied] = useState(false);
  const [awsRef, setAwsRef] = useState("");
  const [cost, setCost] = useState(null);
  const [phase, setPhase] = useState("live");
  const [errorText, setErrorText] = useState("");
  const [createdHost, setCreatedHost] = useState("");
  useEffect(() => {
    api("v1/aws/connect/").then(({ data }) => {
      const reason = data?.reason || "";
      if (!data?.connected && /HUB_AWS_CREDENTIALS_REF/.test(reason)) setAwsRef("");
      else if (data?.connected || reason) setAwsRef("set");
    });
    instanceCreateCost().then(({ status, data }) => {
      setCost(costFromCreateGet(status, data));
    });
  }, []);
  async function onCreate(host) {
    const result = await runCreateTarget(createTarget, host, { zone: "aws-use1" });
    if (!result.ok) {
      setPhase("error");
      setErrorText(TARGET_CREATE_FAILED);
      return;
    }
    setCreatedHost(host);
  }
  if (phase === "error") {
    return (
      <TargetsView phase="error"
        onError={{ text: errorText, retry: () => { setPhase("live"); setErrorText(""); } }} />
    );
  }
  return (
    <div>
      <TargetsView phase="live" targets={[]} awsCredentialsRef={awsRef} cost={cost}
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
