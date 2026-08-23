// Home (§F1 / §F3): the first-run checklist owns this screen until the
// applicable items are done (enroll target; connect CF unless first site is
// mesh_only; plant Origin-CA once a proxied public site exists; add a
// project). After that, Home is today's map + fleet. The fleet half IS the
// readiness surface. Checklist completion is derived; the shell events
// client stays on `findings` (D-045) — do not open a second socket.
import React, { useEffect, useState } from "react";
import ReadinessScreen from "../Readiness.jsx";
import { DESKTOP_MIN_PX, LoadingLine } from "../Chrome.jsx";
import FleetMap from "../Map.jsx";
import { api } from "../api.js";
import { CHECKLIST_COPY, remainingItems } from "../checklist.js";
import { findingsSnapshot } from "./Findings.jsx";
import { PROVISION_CMD } from "./Targets.jsx";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

export function MapPanel({ width, graph, events, sites }) {
  if (width < DESKTOP_MIN_PX) {
    // §F6: the map is explicitly OUT of the phone scope. Saying so beats rendering a
    // squashed unusable one — the phone screens are Sites, Deploys and the finding
    // detail, and this line points at the nearest of them.
    return (
      <p style={{ color: "#8b949e", padding: "0 16px" }}>
        Map is desktop-only — use Sites for status on a phone.</p>
    );
  }
  // Optional `sites` is the §F8 empty/populated fixture. Live Home does not pass it;
  // FleetMap (Task 14) is the graph.
  if (Array.isArray(sites) && sites.length === 0) {
    return (
      <div style={{ ...box, margin: 16, minHeight: 160, color: "#8b949e" }}>
        Map is empty — no sites to place.
      </div>
    );
  }
  if (Array.isArray(sites) && sites.length > 0) {
    return (
      <div style={{ ...box, margin: 16, minHeight: 160, color: "#8b949e" }}>
        Map is populated — {sites.length} sites.
      </div>
    );
  }
  return <FleetMap graph={graph} events={events} />;
}

export async function firstRunSnapshot() {
  const { status, data } = await api("v1/first-run/");
  if (status !== 200 || !data?.data) throw { status };
  return data;
}

export function attachFirstRun(events, onProgress) {
  const load = () => firstRunSnapshot().then((snap) => onProgress(snap.data)).catch(() => {});
  const handler = (event) => {
    if (event.__snapshot_failed) return;
    load();
  };
  events.subscribe("findings", handler, findingsSnapshot);
  return () => events.unsubscribe("findings");
}

function AddProjectForm() {
  const [name, setName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [domain, setDomain] = useState("");
  const [exposure, setExposure] = useState("public");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    const { status, data } = await api("v1/projects/", {
      name, local_path: localPath, domain, exposure, proxied: true,
    });
    setBusy(false);
    if (status === 201) {
      setName(""); setLocalPath(""); setDomain("");
      return;
    }
    const field = Object.values(data.errors ?? {}).flat()[0];
    setError(field?.message ?? data.detail ?? `Unexpected ${status} response.`);
  }

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: 8, maxWidth: 420 }}>
      <label style={{ display: "grid", gap: 4 }}>
        <small>name</small>
        <input aria-label="name" value={name} style={box}
          onChange={(e) => setName(e.target.value)} />
      </label>
      <label style={{ display: "grid", gap: 4 }}>
        <small>local_path</small>
        <input aria-label="local_path" value={localPath} style={box}
          onChange={(e) => setLocalPath(e.target.value)} />
      </label>
      <label style={{ display: "grid", gap: 4 }}>
        <small>domain</small>
        <input aria-label="domain" value={domain} style={box}
          onChange={(e) => setDomain(e.target.value)} />
      </label>
      <label style={{ display: "grid", gap: 4 }}>
        <small>exposure</small>
        <select aria-label="exposure" value={exposure} style={box}
          onChange={(e) => setExposure(e.target.value)}>
          <option value="public">public</option>
          <option value="mesh_only">mesh_only</option>
        </select>
      </label>
      <button style={{ padding: 8 }} disabled={busy}>
        {CHECKLIST_COPY.add_project.button}
      </button>
      {error && <div style={{ color: "#ff7b72" }}>{error}</div>}
    </form>
  );
}

export function ChecklistCard({ progress, onNav }) {
  const items = remainingItems(progress);
  return (
    <div style={{ padding: 16, maxWidth: 640 }}>
      {items.map((item) => {
        const copy = CHECKLIST_COPY[item.id];
        const go = () => {
          if (item.id === "enroll_target") {
            const write = navigator?.clipboard?.writeText;
            if (write) write(PROVISION_CMD);
            else onNav?.("targets");
            return;
          }
          onNav?.("settings");
        };
        return (
          <div key={item.id} style={{ ...box, marginBottom: 12 }}>
            <p>{copy.sentence}</p>
            {item.id === "add_project" ? (
              <AddProjectForm />
            ) : (
              <button style={{ padding: 8 }} onClick={go}>{copy.button}</button>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function HomeView({ width, progress, onNav, events }) {
  if (progress?.owns_home) {
    return <ChecklistCard progress={progress} onNav={onNav} />;
  }
  return (
    <div>
      <MapPanel width={width} events={events} />
      <ReadinessScreen />
    </div>
  );
}

export default function Home({ width, events, onNav }) {
  const [progress, setProgress] = useState(undefined);
  const subscribe = events?.subscribe;
  const unsubscribe = events?.unsubscribe;
  useEffect(() => {
    if (!subscribe) {
      firstRunSnapshot().then((snap) => setProgress(snap.data)).catch(() => {});
      return undefined;
    }
    return attachFirstRun({ subscribe, unsubscribe }, setProgress);
  }, [subscribe, unsubscribe]);
  if (!progress) return <LoadingLine what="home" />;
  return <HomeView width={width} progress={progress} onNav={onNav} events={events} />;
}
