// Home (§F1): the map plus the fleet as ONE composite screen. The fleet half IS the
// readiness surface — project cards with their badges, reports and wizards — reused
// wholesale rather than re-listed, so Home and the sim-reviewed screen cannot drift.
// The map half is a desktop-only region (§F6): at phone width it renders a sentence
// saying where to go instead, and no alert deep link ever routes through it.
import React from "react";
import ReadinessScreen from "../Readiness.jsx";
import { DESKTOP_MIN_PX } from "../Chrome.jsx";
import FleetMap from "../Map.jsx";

export function MapPanel({ width, graph, events }) {
  if (width < DESKTOP_MIN_PX) {
    // §F6: the map is explicitly OUT of the phone scope. Saying so beats rendering a
    // squashed unusable one — the phone screens are Sites, Deploys and the finding
    // detail, and this line points at the nearest of them.
    return (
      <p style={{ color: "#8b949e", padding: "0 16px" }}>
        Map is desktop-only — use Sites for status on a phone.</p>
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
