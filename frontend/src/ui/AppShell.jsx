import React, { useEffect, useState } from "react";
import { NAV } from "../Chrome.jsx";
import { SideNav } from "./SideNav.jsx";
import { TopBar } from "./TopBar.jsx";
import { ADMIN_NAV } from "../screens/administration/admin-nav.js";
import { adminCrumbs } from "../screens/administration/admin-nav.js";
import { api } from "../api.js";

export function HudAppShell({
  user,
  events,
  route,
  onNav,
  onLogout,
  children,
  shell,
}) {
  const admin = route.screen === "admin";
  const items = admin ? ADMIN_NAV : NAV;
  const current = admin ? (route.id || "overview").split("/")[0] : route.screen;
  const [snap, setSnap] = useState(shell || { p1_p2: 0, scope: "production", operations: [] });

  useEffect(() => {
    if (shell) {
      setSnap(shell);
      return undefined;
    }
    if (!admin) return undefined;
    let cancelled = false;
    api("v1/hud/shell/").then(({ status, data }) => {
      if (!cancelled && status === 200) setSnap(data);
    });
    return () => { cancelled = true; };
  }, [admin, shell, route]);

  return (
    <div className="hud-shell">
      <a className="hud-skip" href="#main">Skip to main content</a>
      <TopBar
        title="Deploy Hub"
        crumbs={admin ? adminCrumbs(route) : [{ label: "Operator Console" }]}
        events={events}
        user={user}
        onNav={onNav}
        onLogout={onLogout}
        workspace={admin ? "admin" : "operator"}
        shell={snap}
        route={route}
      />
      <SideNav
        items={items}
        current={current}
        compact={typeof window !== "undefined" && window.innerWidth && window.innerWidth < 900}
        label={admin ? "Administration" : "Operator"}
        onNav={(id) => {
          if (admin) {
            if (id === "home") onNav("home");
            else onNav("admin", id);
          } else {
            onNav(id);
          }
        }}
      />
      <main id="main" className="hud-main">
        {children}
      </main>
    </div>
  );
}

export { NAV };
