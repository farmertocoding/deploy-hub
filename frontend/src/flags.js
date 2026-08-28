// hud_ui_v1 (HUD-D7 / D-146): capability/flag with the previous shell as rollback.
// ?hud=0 restores the pre-HUD chrome without touching deployment/audit/secret records.

export function searchParams(search) {
  try {
    const raw = search ?? (typeof window !== "undefined" ? window.location.search : "");
    return new URLSearchParams(raw || "");
  } catch {
    return new URLSearchParams();
  }
}

export function capabilitiesOf(user) {
  return Array.isArray(user?.capabilities) ? user.capabilities : [];
}

export function hasCapability(user, name) {
  return capabilitiesOf(user).includes(name);
}

export function hudUiEnabled(user, search) {
  const params = searchParams(search);
  if (params.get("hud") === "0") return false;
  if (params.get("hud") === "1") return true;
  if (typeof user?.hud_ui === "boolean") return user.hud_ui;
  return hasCapability(user, "hud_ui_v1");
}

export function adminReadEnabled(user) {
  return hasCapability(user, "admin_read");
}

export function systemAdminEnabled(user) {
  return Boolean(user?.is_system_admin);
}
