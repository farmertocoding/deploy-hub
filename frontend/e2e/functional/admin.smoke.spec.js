import { test, expect } from "@playwright/test";
import { ADMIN_SMOKE_ROUTES, openHud, waitAdminReady } from "../helpers.js";

for (const route of ADMIN_SMOKE_ROUTES) {
  test(`admin ${route.name} loads under ?sim=live`, async ({ page }) => {
    await openHud(page, { hash: `#/admin/${route.hash}` });
    await waitAdminReady(page, route.heading);
    await expect(page.getByRole("navigation", { name: /Administration/i })).toBeVisible();
  });
}

test("unknown admin screen falls back to overview", async ({ page }) => {
  await openHud(page, { hash: "#/admin/not-a-screen" });
  await waitAdminReady(page, "Fleet overview");
});
