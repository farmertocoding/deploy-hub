import { test, expect } from "@playwright/test";
import { ADMIN_ROUTES, openAdminRoute } from "./admin-test-helpers.js";

for (const theme of ["dark", "light"]) {
  for (const route of ADMIN_ROUTES) {
    test(`${route.name} is visually stable in ${theme} theme`, async ({ page }) => {
      await openAdminRoute(page, route, theme);
      await expect(page).toHaveScreenshot(`${route.name}-${theme}-desktop.png`, {
        fullPage: true,
      });
    });
  }
}

test("overview is visually stable at the compact navigation breakpoint", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1000 });
  await openAdminRoute(page, ADMIN_ROUTES[0], "dark");
  await expect(page).toHaveScreenshot("overview-dark-compact.png", { fullPage: true });
});
