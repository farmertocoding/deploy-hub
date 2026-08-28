# Deploy Hub Design Concepts

These images are operational UI concepts, not decorative mood boards. Their behavior is defined in [Functional Screen Contract](functional-screen-contract.md).

## Current high-fidelity concepts

1. [Fleet overview — HUD dark](01-fleet-overview-hud-dark-v3.png) — fleet risk, live work, health, integrations, setup readiness, and the functional appearance selector.
2. [Sites fleet — HUD light](02-sites-fleet-hud-light-v3.png) — search, filtering, drift detection, contextual next actions, and the selected light appearance.
3. [Live deployment — HUD dark](03-live-deployment-hud-dark-v3.png) — impact, serving state, nine deployment steps, health evidence, and recovery controls.
4. [Access and secrets — HUD light](04-access-secrets-hud-light-v3.png) — membership entry points, Vault metadata, reference health, secret lifecycle actions, and security policy.

The material system and measured dark/light values are defined in [HUD Style Fidelity Specification](hud-style-fidelity-spec.md).

The ordered repository-specific delivery plan, ownership model, quality gates, and rollout controls are defined in [Production Implementation Plan](production-implementation-plan.md).

Earlier PNGs are retained as visual iteration history. The `*-v3.png` files are the current design direction.

## Implementation rule

Do not implement a visible control until its purpose, destination or effect, permission, availability, feedback, and audit outcome are defined. Remove any element that cannot satisfy that rule.
