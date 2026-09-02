# Frontend browser quality gates

These Playwright checks use the built-in `?sim=live` HUD fixtures, so they do not
need Django, Docker, credentials, or production data. A deterministic WebSocket stub
keeps screenshots focused on UI layout; the real socket state machine remains covered
by the unit suite.

## One-time setup

```bash
npm ci
npx playwright install chromium
```

Linux CI should use `npx playwright install --with-deps chromium`.

## Commands

```bash
npm run test:e2e          # visual and WCAG 2.1 AA checks
npm run test:visual       # screenshot comparisons only
npm run test:a11y         # axe semantics and color-contrast checks only
npm run test:visual:update # intentionally approve new screenshot baselines
npm run test:functional   # functional + adversarial specs (no screenshots)
```

Never update baselines merely to make CI green. Review the Playwright HTML diff,
check dark and light themes, and confirm the change is intentional before committing
new images. Browser artifacts are written to `playwright-report/` and `test-results/`
and are ignored by Git.

## Functional + adversarial

```bash
npm run test:functional
```

These specs always navigate with `?sim=` (shared helpers in `helpers.js`); they never use
`vite preview`. Keep `ADMIN_ROUTES` in `admin-test-helpers.js` frozen for visual/a11y —
do not grow it. Functional and adversarial specs must not call `toHaveScreenshot` or
update visual snapshots. Loading-hang cases assert the spinner and stop.
