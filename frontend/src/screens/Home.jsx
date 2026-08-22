// Home (§F1): the map plus the fleet as ONE composite screen. The fleet half IS the
// readiness surface — project cards with their badges, reports and wizards — reused
// wholesale rather than re-listed, so Home and the sim-reviewed screen cannot drift.
// The map half is a desktop-only region (§F6): at phone width it renders a sentence
// saying where to go instead, and no alert deep link ever routes through it.
import React from "react";
import ReadinessScreen from "../Readiness.jsx";
import { DESKTOP_MIN_PX } from "../Chrome.jsx";
import FleetMap from "../Map.jsx";

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

export default function Home({ width, events }) {
  return (
    <div>
      <MapPanel width={width} events={events} />
      <ReadinessScreen />
    </div>
  );
}
