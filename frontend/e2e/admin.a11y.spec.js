import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "@playwright/test";
import { ADMIN_ROUTES, openAdminRoute } from "./admin-test-helpers.js";

const WCAG_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

function violationSummary(violations) {
  return violations.map((violation) => {
    const nodes = violation.nodes
      .map((node) => `${node.target.join(" ")}: ${node.failureSummary || node.html}`)
      .join("\n    ");
    return `${violation.id} (${violation.impact}): ${violation.help}\n    ${nodes}`;
  }).join("\n\n");
}

for (const theme of ["dark", "light"]) {
  for (const route of ADMIN_ROUTES) {
    test(`${route.name} meets WCAG 2.1 AA in ${theme} theme`, async ({ page }) => {
      await openAdminRoute(page, route, theme);
      const results = await new AxeBuilder({ page })
        .include("#root")
        .withTags(WCAG_AA)
        .analyze();

      if (results.violations.length) {
        throw new Error(violationSummary(results.violations));
      }
      expect(results.violations).toHaveLength(0);
    });
  }
}
