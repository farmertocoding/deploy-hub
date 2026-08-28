import React from "react";

export function Chart({ title, range, points = [], legend = [] }) {
  const max = Math.max(1, ...points.map((p) => Number(p.value) || 0));
  const w = 280;
  const h = 80;
  const d = points.map((p, i) => {
    const x = points.length <= 1 ? 0 : (i / (points.length - 1)) * w;
    const y = h - ((Number(p.value) || 0) / max) * h;
    return `${i === 0 ? "M" : "L"}${x},${y}`;
  }).join(" ");
  return (
    <figure className="hud-chart">
      <figcaption>
        <strong>{title}</strong>
        {range ? <span> — {range}</span> : null}
      </figcaption>
      <svg width={w} height={h} role="img" aria-label={title}>
        <path d={d || "M0,80"} fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
      {legend.length ? (
        <ul>
          {legend.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : (
        <table>
          <caption>{title} values</caption>
          <tbody>
            {points.map((p) => (
              <tr key={p.label}><td>{p.label}</td><td>{p.value}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </figure>
  );
}
