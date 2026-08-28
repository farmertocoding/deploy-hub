import React, { useEffect, useState } from "react";
import { StatusPill } from "../Chrome.jsx";
import { Status } from "./Status.jsx";
import { AppearanceMenu } from "./AppearanceMenu.jsx";
import { WorkspaceMenu } from "./WorkspaceMenu.jsx";
import { Button } from "./Button.jsx";
import { HudFrame } from "./HudFrame.jsx";
import { api, simState } from "../api.js";
import { adminHref, parseHashQuery } from "../screens/administration/contract.js";

export function TopBar({
  title = "Deploy Hub",
  crumb,
  crumbs,
  events,
  user,
  onNav,
  workspace = "operator",
  shell = {},
  route,
}) {
  const sim = simState();
  const eventStatus = sim && sim !== "error" && sim !== "degraded"
    ? "live"
    : (sim === "degraded" || sim === "error" ? "degraded" : events?.status);
  const liveAdmin = workspace === "admin" && eventStatus === "live";
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [opsOpen, setOpsOpen] = useState(false);
  const [liveOpen, setLiveOpen] = useState(false);
  const p1p2 = shell.p1_p2 ?? 0;
  const hashQuery = { ...(route?.query || {}), ...parseHashQuery() };
  const scope = hashQuery.scope || shell.scope || "production";
  const operations = shell.operations || [];
  const trail = crumbs || (crumb ? [{ label: crumb }] : []);

  useEffect(() => {
    if (!query || workspace !== "admin") {
      setResults(null);
      return undefined;
    };
    const handle = setTimeout(() => {
      api(`v1/hud/search/?q=${encodeURIComponent(query)}`).then(({ status, data }) => {
        if (status === 200) setResults(data.groups || []);
      });
    }, 200);
    return () => clearTimeout(handle);
  }, [query, workspace]);

  return (
    <header className="hud-header">
      <span className="hud-brand">{title}</span>
      {shell.build_id ? <span className="hud-kicker" title="Build">build {String(shell.build_id).slice(0, 8)}</span> : null}
      {trail.length ? (
        <nav aria-label="Breadcrumb" className="hud-crumb">
          {trail.map((item, i) => {
            const last = i === trail.length - 1;
            return (
              <span key={`${item.label}-${i}`}>
                {i > 0 ? " / " : null}
                {last || !item.screen ? (
                  <span aria-current={last ? "page" : undefined}>{item.label}</span>
                ) : (
                  <button
                    type="button"
                    className="hud-btn hud-btn--quiet"
                    onClick={() => onNav(item.screen, item.id)}
                  >
                    {item.label}
                  </button>
                )}
              </span>
            );
          })}
        </nav>
      ) : null}
      {workspace === "admin" ? (
        <Button
          variant="quiet"
          aria-label="Environment scope"
          onClick={() => {
            const next = scope === "production" ? "test" : "production";
            const path = String(route?.id || "overview").split("?")[0] || "overview";
            onNav?.("admin", adminHref(path, { ...hashQuery, scope: next }));
          }}
        >
          {scope === "test" ? "Test" : "Production"}
        </Button>
      ) : null}
      {workspace === "admin" ? (
        <label className="hud-search">
          <input
            aria-label="Global search"
            role="combobox"
            aria-expanded={Boolean(results)}
            aria-controls="hud-search-listbox"
            aria-autocomplete="list"
            value={query}
            placeholder="Project, site, target, deployment, finding, partner"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") { setQuery(""); setResults(null); } }}
          />
          {results ? (
            <div className="hud-search__results" role="listbox" id="hud-search-listbox">
              {results.map((group) => (
                <div key={group.kind}>
                  <p className="hud-kicker">{group.kind}</p>
                  {(group.results || []).map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      className="hud-appearance__choice"
                      onClick={() => {
                        setQuery("");
                        setResults(null);
                        onNav("admin", item.href);
                      }}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          ) : null}
        </label>
      ) : null}
      <span className="hud-header-spacer" />
      {workspace === "admin" ? (
        <Button variant="navigation" onClick={() => onNav("admin", adminHref("findings", { ...hashQuery, facet: "p1p2" }))}>
          {p1p2} P1/P2
        </Button>
      ) : null}
      {workspace === "admin" ? (
        <div className="hud-ops">
          <Button
            variant="quiet"
            aria-label="Operations"
            aria-expanded={opsOpen}
            onClick={() => setOpsOpen((v) => !v)}
          >
            Operations
          </Button>
          {opsOpen ? (
            <div className="hud-ops__drawer">
              <HudFrame variant="popover">
                <h2 className="hud-kicker">Operations</h2>
                {operations.length === 0 ? <p>No asynchronous operations.</p> : operations.map((op) => (
                  <p key={op.id}><Status state={op.state} /> {op.label}</p>
                ))}
              </HudFrame>
            </div>
          ) : null}
        </div>
      ) : null}
      {liveAdmin ? (
        <div className="hud-live">
          <button
            type="button"
            className="hud-btn hud-btn--quiet"
            aria-label="Connection status"
            aria-expanded={liveOpen}
            onClick={() => setLiveOpen((v) => !v)}
          >
            <Status state="live" />
          </button>
          {liveOpen ? (
            <div className="hud-live__popover">
              <HudFrame variant="popover">
                <p className="hud-kicker">Connection</p>
                <p>Transport multiplexed events</p>
                <p>Last event {events?.asOf || "now"}</p>
                <p>Last successful refresh {events?.asOf || "now"}</p>
              </HudFrame>
            </div>
          ) : null}
        </div>
      ) : (
        <StatusPill status={eventStatus} asOf={events?.asOf} />
      )}
      <AppearanceMenu />
      <WorkspaceMenu user={user} onNav={onNav} />
    </header>
  );
}
