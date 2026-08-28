export const ADMIN_NAV = [
  { id: "overview", label: "Overview" },
  { id: "projects", label: "Projects" },
  { id: "sites", label: "Sites" },
  { id: "deployments", label: "Deployments" },
  { id: "targets", label: "Targets" },
  { id: "findings", label: "Findings & Operations" },
  { id: "partners", label: "Partners" },
  { id: "secrets", label: "Access & Secrets" },
  { id: "integrations", label: "Integrations & DNS" },
  { id: "audit", label: "Audit" },
];

export function parseAdminId(route) {
  const raw = route?.id || "overview";
  const [adminScreen, objectId] = String(raw).split("/");
  const known = ADMIN_NAV.some((n) => n.id === adminScreen);
  return {
    adminScreen: known ? adminScreen : "overview",
    objectId: objectId || undefined,
  };
}

export function adminCrumbs(route) {
  const { adminScreen, objectId } = parseAdminId(route);
  const item = ADMIN_NAV.find((n) => n.id === adminScreen);
  const crumbs = [
    { label: "Administration", screen: "admin", id: "overview" },
  ];
  if (adminScreen && adminScreen !== "overview") {
    crumbs.push({ label: item?.label || adminScreen, screen: "admin", id: adminScreen });
  }
  if (objectId) {
    crumbs.push({ label: objectId });
  }
  return crumbs;
}
