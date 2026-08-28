import React from "react";
import { Status } from "./Status.jsx";

export function Timeline({ steps = [] }) {
  return (
    <ol className="hud-timeline">
      {steps.map((s) => (
        <li key={s.name}>
          <Status state={s.state || s.status || "pending"} />
          {" "}
          {s.label || s.name}
        </li>
      ))}
    </ol>
  );
}
