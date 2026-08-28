// Map v1 (MAP-96-GRAPH-V1, D-041): plain SVG + list-view toggle. No graph lib.
// Status is icon + label, never colour-only. Zone groups nest hosts; containers
// collapse to a count chip above CHIP_AFTER children. Desktop-only caller
// (Home MapPanel / §F6) decides whether this mounts at all.
import React, { useEffect, useState } from "react";
import { api } from "./api.js";

import { box } from "./ui/surface.js";

export const CHIP_AFTER = 6;

const STATUS_ICON = {
  ok: "✓",
  ready: "✓",
  pending: "…",
  error: "⛔",
  decommissioned: "×",
  running: "▶",
  stopped: "■",
  absent: "○",
  unhealthy: "⚠",
  warming: "↻",
  ghost: "◌",
};

export function statusMark(status) {
  return `${STATUS_ICON[status] || "•"} ${status}`;
}

function isEmptyFleet(nodes) {
  return !(nodes || []).some((n) =>
    n.kind === "zone" || n.kind === "host" || n.kind === "container"
    || n.kind === "ghost");
}

export function MapView({ graph, listView = false, onToggle }) {
  const nodes = graph?.nodes || [];
  const edges = graph?.edges || [];
  const empty = isEmptyFleet(nodes);

  return (
    <div style={{ ...box, margin: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>Fleet map</h2>
        <button style={box} type="button" onClick={onToggle}>
          {listView ? "Map view" : "List view"}
        </button>
      </div>
      {empty ? (
        <p style={{ color: "var(--hud-muted)" }}>
          No hosts yet — provision a target and the fleet draws here.
        </p>
      ) : listView ? (
        <ul style={{ listStyle: "none", padding: 0, margin: "12px 0 0" }}>
          {nodes.map((n) => (
            <li key={n.id} data-status={n.status} style={{ padding: "4px 0" }}>
              {n.label}{" "}
              <span data-status={n.status}>{statusMark(n.status)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <SvgGraph nodes={nodes} edges={edges} />
      )}
    </div>
  );
}

function FindingChips({ node, x, y }) {
  // Optional topology chips: hash-router deep links, never a path the SPA
  // does not mount. Severity is the label (not colour-only).
  const items = node.findings || [];
  if (!items.length) return null;
  return (
    <g data-kind="finding-chips">
      {items.map((f, i) => (
        <a key={f.id} href={`#/findings/${f.id}`}>
          <text x={x + 8} y={y - 12 - i * 12} fill="var(--hud-warning)" fontSize="11"
            data-finding-id={f.id}>
            {String(f.severity || "").toUpperCase()}
          </text>
        </a>
      ))}
    </g>
  );
}

function SvgGraph({ nodes, edges }) {
  const pos = layout(nodes);
  const width = Math.max(640, ...Object.values(pos).map((p) => (p.x || 0) + (p.w || 40) + 24));
  const height = Math.max(220, ...Object.values(pos).map((p) => (p.y || 0) + (p.h || 24) + 24));
  const containers = nodes.filter((n) => n.kind === "container");
  const hosts = nodes.filter((n) => n.kind === "host");
  const chipFor = {};
  for (const host of hosts) {
    const kids = containers.filter((c) => c.parent === host.id);
    if (kids.length > CHIP_AFTER) chipFor[host.id] = kids.length;
  }

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ marginTop: 12 }}
      role="img" aria-label="Fleet topology">
      {edges.map((e) => {
        const a = pos[e.a], b = pos[e.b];
        if (!a || !b) return null;
        return (
          <line key={`${e.a}-${e.b}-${e.path}`}
            data-path={e.path}
            x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            stroke="var(--hud-muted)" strokeWidth="1.5"
            strokeDasharray={e.path === "mesh" ? "6 4" : "0"} />
        );
      })}
      {nodes.filter((n) => n.kind === "zone").map((n) => {
        const p = pos[n.id];
        return (
          <g key={n.id} data-kind="zone">
            <rect x={p.x - 16} y={p.y - 20} width={p.w} height={p.h}
              fill="none" stroke="#333" rx="6" />
            <NodeLabel node={n} x={p.x} y={p.y} />
            <FindingChips node={n} x={p.x} y={p.y} />
          </g>
        );
      })}
      {nodes.filter((n) => n.kind !== "zone" && n.kind !== "container").map((n) => {
        const p = pos[n.id];
        if (!p) return null;
        return (
          <g key={n.id} data-kind={n.kind}>
            <NodeLabel node={n} x={p.x} y={p.y} />
            <FindingChips node={n} x={p.x} y={p.y} />
            {chipFor[n.id] != null && (
              <text x={p.x} y={p.y + 16} fill="var(--hud-muted)" fontSize="11">
                {chipFor[n.id]} containers
              </text>
            )}
          </g>
        );
      })}
      {nodes.filter((n) => n.kind === "container" && !chipFor[n.parent]).map((n) => {
        const p = pos[n.id];
        if (!p) return null;
        return (
          <g key={n.id} data-kind="container">
            <NodeLabel node={n} x={p.x} y={p.y} />
            <FindingChips node={n} x={p.x} y={p.y} />
          </g>
        );
      })}
    </svg>
  );
}

function NodeLabel({ node, x, y }) {
  return (
    <text x={x} y={y} fill="#e6e6e6" fontSize="12">
      <tspan data-status={node.status}>{statusMark(node.status)}</tspan>
      {"  "}{node.label}
    </text>
  );
}

function layout(nodes) {
  const pos = {
    hub: { x: 80, y: 28 },
    edge: { x: 420, y: 28 },
  };
  const zones = nodes.filter((n) => n.kind === "zone");
  const hosts = nodes.filter((n) => n.kind === "host");
  const ghosts = nodes.filter((n) => n.kind === "ghost");
  const containers = nodes.filter((n) => n.kind === "container");
  const zoneW = 280;
  const zoneH = 160;
  zones.forEach((z, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    pos[z.id] = {
      x: 40 + col * (zoneW + 20),
      y: 70 + row * (zoneH + 20),
      w: zoneW,
      h: zoneH,
    };
  });
  const hostsByZone = new Map();
  for (const h of [...hosts, ...ghosts.filter((g) => g.parent)]) {
    const key = h.parent || "_";
    if (!hostsByZone.has(key)) hostsByZone.set(key, []);
    hostsByZone.get(key).push(h);
  }
  for (const [zoneId, group] of hostsByZone) {
    const zp = pos[zoneId] || { x: 40, y: 70, w: zoneW, h: zoneH };
    group.forEach((h, i) => {
      pos[h.id] = { x: zp.x + 8 + (i % 2) * 130, y: zp.y + 36 + Math.floor(i / 2) * 48 };
    });
  }
  let fallbackY = 70;
  for (const z of zones) {
    const p = pos[z.id];
    if (p) fallbackY = Math.max(fallbackY, p.y + (p.h || zoneH));
  }
  ghosts.filter((g) => !g.parent).forEach((g, i) => {
    pos[g.id] = { x: 40, y: fallbackY + 24 + i * 24 };
  });
  const kidsByHost = new Map();
  for (const c of containers) {
    const key = c.parent || "_";
    if (!kidsByHost.has(key)) kidsByHost.set(key, []);
    kidsByHost.get(key).push(c);
  }
  for (const [hostId, kids] of kidsByHost) {
    if (kids.length > CHIP_AFTER) continue;
    const hp = pos[hostId] || { x: 40, y: 70 };
    kids.forEach((c, i) => {
      pos[c.id] = { x: hp.x, y: hp.y + 16 + i * 12 };
    });
  }
  return pos;
}

// GET v1/map/ is the map.graph snapshot (§D7) — not topics/${topic}/snapshot/.
export async function mapGraphSnapshot() {
  const { status, data } = await api("v1/map/");
  if (status !== 200 || !data?.data) throw { status };
  return data;
}

// Snapshot-then-stream bind: the shell's one client already exists; this is
// subscribe("map.graph", handler, snapshotFn). Event payload is {kind: changed},
// not the graph — refetch (or apply __snapshot) the same way other table-backed
// topics do. Exported so tests can drive the handler without mount effects.
export function attachMapGraph(events, onGraph) {
  const handler = (event) => {
    if (event.__snapshot) {
      onGraph(event.data);
      return;
    }
    if (event.__snapshot_failed) return;
    if (event.kind === "changed") {
      mapGraphSnapshot().then((snap) => onGraph(snap.data)).catch(() => {});
    }
  };
  events.subscribe("map.graph", handler, mapGraphSnapshot);
  return () => events.unsubscribe("map.graph");
}

export default function FleetMap({ graph: graphProp, events }) {
  const [listView, setListView] = useState(false);
  const [graph, setGraph] = useState(graphProp || { nodes: [], edges: [] });
  // Key the bind on subscribe identity — useEvents reallocates the wrapper
  // object on every status/asOf tick; depending on `events` would unsubscribe
  // and snapshot-loop.
  const subscribe = events?.subscribe;
  const unsubscribe = events?.unsubscribe;

  useEffect(() => {
    if (graphProp) {
      setGraph(graphProp);
      return undefined;
    }
    if (!subscribe) return undefined;
    return attachMapGraph({ subscribe, unsubscribe }, setGraph);
  }, [subscribe, unsubscribe, graphProp]);

  return (
    <MapView graph={graph} listView={listView}
      onToggle={() => setListView((v) => !v)} />
  );
}
