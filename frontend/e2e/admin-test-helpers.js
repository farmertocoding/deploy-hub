import { expect } from "@playwright/test";

export const ADMIN_ROUTES = [
  { name: "overview", hash: "overview", heading: "Fleet overview" },
  { name: "sites", hash: "sites", heading: "Sites Fleet" },
  { name: "deployment", hash: "deployments/11", heading: "Deployment" },
];

export async function prepareHud(page, theme = "dark") {
  await page.addInitScript((selectedTheme) => {
    localStorage.setItem("deploy-hub.appearance.v1", selectedTheme);

    // Keep the connection indicator deterministic. Browser coverage here is for
    // layout and accessibility; the socket state machine has dedicated unit tests.
    class StableWebSocket {
      constructor() {
        this.readyState = 0;
        queueMicrotask(() => {
          this.readyState = 1;
          this.onopen?.({});
        });
      }

      send() {}

      close() {
        this.readyState = 3;
      }
    }
    window.WebSocket = StableWebSocket;
  }, theme);
}

export async function openAdminRoute(page, route, theme = "dark") {
  await prepareHud(page, theme);
  await page.goto(`/?sim=live#/admin/${route.hash}`);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.getByRole("heading", { name: new RegExp(route.heading, "i") }).first()).toBeVisible();
  await expect(page.getByRole("status", { name: /Loading Administration/i })).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
}
