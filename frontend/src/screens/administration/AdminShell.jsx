import React from "react";
import { parseAdminId } from "./admin-nav.js";
import Overview from "./Overview.jsx";
import SitesFleet from "./SitesFleet.jsx";
import LiveDeployment from "./LiveDeployment.jsx";
import AccessSecrets from "./AccessSecrets.jsx";
import Projects from "./Projects.jsx";
import Deployments from "./Deployments.jsx";
import Targets from "./Targets.jsx";
import FindingsOps from "./FindingsOps.jsx";
import Partners from "./Partners.jsx";
import Integrations from "./Integrations.jsx";
import Audit from "./Audit.jsx";
import SiteDetail from "./SiteDetail.jsx";
import { AsyncRegion } from "../../ui/AsyncRegion.jsx";
import { adminReadEnabled } from "../../flags.js";

const SCREENS = {
  overview: Overview,
  projects: Projects,
  sites: SitesFleet,
  deployments: Deployments,
  targets: Targets,
  findings: FindingsOps,
  partners: Partners,
  secrets: AccessSecrets,
  integrations: Integrations,
  audit: Audit,
};

export { SCREENS };

export default function AdminShell({ route, onNav, width, events, user, onReloadPermissions }) {
  if (user && user.authenticated === false) {
    return (
      <AsyncRegion
        phase="signed-out"
        onSignIn={() => {
          if (typeof window !== "undefined") window.location.hash = "#/";
          onReloadPermissions?.();
        }}
      />
    );
  }
  if (!adminReadEnabled(user)) {
    return (
      <AsyncRegion
        phase="permission-denied"
        deniedReason={
          user?.capabilitiesChanged
            ? "Your administration permissions changed during this session."
            : "Administration is a separate workspace. This account lacks admin_read."
        }
        onReloadPermissions={onReloadPermissions}
        onReturnToOperator={() => onNav("home")}
      />
    );
  }
  const { adminScreen, objectId } = parseAdminId(route);
  if (adminScreen === "deployments" && objectId) {
    return <LiveDeployment route={route} onNav={onNav} width={width} events={events} user={user} />;
  }
  if (adminScreen === "sites" && objectId && objectId !== "new") {
    return <SiteDetail route={route} onNav={onNav} width={width} events={events} user={user} />;
  }
  const Screen = SCREENS[adminScreen] || Overview;
  return (
    <Screen
      route={route}
      onNav={onNav}
      width={width}
      events={events}
      user={user}
      onReloadPermissions={onReloadPermissions}
    />
  );
}
