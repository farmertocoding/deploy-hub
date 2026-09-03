import { test, expect } from "@playwright/test";
import { openOperator } from "../helpers.js";

test("rapid hash navigation does not crash the shell", async ({ page }) => {
  await openOperator(page, { hash: "#/" });
  const hops = ["#/sites", "#/targets", "#/findings", "#/settings", "#/admin/overview", "#/admin/sites", "#/admin/deployments/11", "#/"];
  for (const hash of hops) {
    await page.evaluate((h) => { window.location.hash = h; }, hash);
  }
  await expect(page.locator("#root")).not.toBeEmpty();
  await expect(page.getByText(/Something went wrong|Minified React error/i)).toHaveCount(0);
});
