import { expect } from "@playwright/test";
import { prepareHud } from "./admin-test-helpers.js";

export const ADMIN_SMOKE_ROUTES = [
  { name: "overview", hash: "overview", heading: "Fleet overview" },
  { name: "projects", hash: "projects", heading: "Projects" },
  { name: "sites", hash: "sites", heading: "Sites fleet" },
  { name: "deployments", hash: "deployments", heading: "Deployments" },
  { name: "live-deployment", hash: "deployments/11", heading: "Live deployment" },
  { name: "site-detail", hash: "sites/1", heading: "shop/prod" },
  { name: "targets", hash: "targets", heading: "Targets" },
  { name: "findings", hash: "findings", heading: "Findings & Operations" },
  { name: "partners", hash: "partners", heading: "Partners" },
  { name: "secrets", hash: "secrets", heading: "Access & Secrets" },
  { name: "integrations", hash: "integrations", heading: "Integrations & DNS" },
  { name: "audit", hash: "audit", heading: "Audit" },
];

export const OPERATOR_NAV = ["Home", "Sites", "Targets", "Deploys", "Findings", "Settings"];

export function simUrl(state, hash = "", extraSearch = "") {
  if (!state) throw new Error("simUrl requires a sim state — omitting ?sim= would proxy to Django");
  const extra = extraSearch ? `&${extraSearch.replace(/^[?&]/, "")}` : "";
  const fragment = hash ? (hash.startsWith("#") ? hash : `#/${hash.replace(/^#\/?/, "")}`) : "";
  return `/?sim=${state}${extra}${fragment}`;
}

export async function openHud(page, { sim = "live", hash = "#/admin/overview", theme = "dark", stubSocket = true } = {}) {
  if (stubSocket) await prepareHud(page, theme);
  else {
    await page.addInitScript((selectedTheme) => {
      localStorage.setItem("deploy-hub.appearance.v1", selectedTheme);
    }, theme);
  }
  await page.goto(simUrl(sim, hash));
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

export async function openOperator(page, { sim = "live", hash = "#/", theme = "dark" } = {}) {
  await prepareHud(page, theme);
  await page.goto(simUrl(sim, hash));
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

export async function openAuth(page, sim) {
  if (!["login", "enroll", "t1"].includes(sim)) throw new Error(`openAuth: unexpected sim ${sim}`);
  await page.goto(simUrl(sim));
}

export async function waitAdminReady(page, heading) {
  await expect(page.getByRole("heading", { name: new RegExp(heading, "i") }).first()).toBeVisible();
  await expect(page.getByRole("status", { name: /Loading Administration/i })).toHaveCount(0);
}
