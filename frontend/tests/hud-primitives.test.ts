import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };

import { HudFrame } from "../src/ui/HudFrame.jsx";
import { Button } from "../src/ui/Button.jsx";
import { Status, statusParts } from "../src/ui/Status.jsx";
import { Timeline } from "../src/ui/Timeline.jsx";
import { fillDeploySteps, LiveDeploymentView } from "../src/screens/administration/LiveDeployment.jsx";
import { AccessSecretsView, secretLeakFields } from "../src/screens/administration/AccessSecrets.jsx";
import { OverviewView } from "../src/screens/administration/Overview.jsx";
import { HUD_DEPLOY_FIXTURE, HUD_OVERVIEW_FIXTURE, HUD_SECRET_FIXTURE } from "../src/hud-sim.js";
import { DEPLOY_STEP_NAMES } from "../src/screens/Deploys.jsx";
import { StatusPill } from "../src/Chrome.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

test("hud_frame_renders_four_decorative_corners_once", () => {
  const markup = render(HudFrame, { variant: "panel", children: "body" });
  const corners = markup.match(/hud-frame__corner--/g) || [];
  assert.equal(corners.length, 4);
  assert.match(markup, /hud-frame__corner--tl/);
  assert.match(markup, /hud-frame__corner--tr/);
  assert.match(markup, /hud-frame__corner--br/);
  assert.match(markup, /hud-frame__corner--bl/);
  assert.match(markup, /aria-hidden="true"/);
  assert.doesNotMatch(markup, /backdrop-filter/);
  assert.equal((markup.match(/hud-frame /g) || []).length, 1);
});

test("busy_button_keeps_stable_label", () => {
  const idle = render(Button, { children: "Abort and clean up", busy: false });
  const busy = render(Button, { children: "Abort and clean up", busy: true });
  assert.match(visibleText(idle), /Abort and clean up/);
  assert.match(visibleText(busy), /Abort and clean up/);
  assert.match(busy, /aria-busy="true"/);
  assert.equal(visibleText(idle).includes("Abort and clean up"), true);
});

test("disabled_action_exposes_reason_in_markup", () => {
  const markup = render(Button, {
    children: "Export",
    disabled: true,
    disabledReason: "This kind is not exportable.",
  });
  assert.match(markup, /This kind is not exportable/);
  assert.match(markup, /aria-describedby/);
  assert.match(markup, /aria-disabled="true"/);
});

test("status_always_includes_symbol_and_word", () => {
  for (const state of ["running", "failed", "p1", "healthy", "degraded"]) {
    const markup = render(Status, { state });
    const { symbol, word } = statusParts(state);
    const text = visibleText(markup);
    assert.ok(text.includes(symbol), state);
    assert.ok(text.includes(word), state);
  }
});

test("operator_live_status_pill_still_renders_nothing", () => {
  assert.equal(render(StatusPill, { status: "live", asOf: null }), "");
  const degraded = render(StatusPill, { status: "degraded", asOf: new Date(2026, 7, 27, 12, 0, 0) });
  assert.match(visibleText(degraded), /data as of/);
});

test("live_deployment_fills_nine_named_steps_when_payload_omits_some", () => {
  const steps = fillDeploySteps({ steps: [{ name: "build", state: "succeeded" }] });
  assert.deepEqual(steps.map((s) => s.name), DEPLOY_STEP_NAMES);
  assert.equal(steps[1].state, "pending");
  const markup = render(LiveDeploymentView, {
    deploy: {
      ...HUD_DEPLOY_FIXTURE,
      steps: [{ name: "build", state: "succeeded" }],
    },
  });
  const text = visibleText(markup);
  for (const label of [
    "Build", "Ship", "Migrate", "Start green", "Health check",
    "DNS", "Smoke test", "Cutover",
  ]) {
    assert.ok(text.includes(label), label);
  }
  assert.match(text, /Route/);
  assert.match(text, /TLS/);
  assert.ok(!/Delete Deployment/i.test(text));
  assert.ok(!/KEEP WATCHING/i.test(text));
  assert.ok(!/Keep watching/i.test(text));
  assert.match(text, /Rollback target: v3/);
  assert.match(text, /Serving v3/);
  assert.match(text, /desired v4/);
  assert.match(text, /View site health/i);
  assert.match(text, /Copy ID/);
  assert.match(text, /View live log/i);
  assert.match(text, /View artifacts/i);
  assert.match(text, /View full audit trail/i);
  assert.match(text, /Abort and clean up/);
});

test("timeline_lists_pending_for_missing_steps", () => {
  const markup = render(Timeline, { steps: fillDeploySteps({ steps: [] }) });
  assert.equal((markup.match(/<li/g) || []).length, 9);
});

test("access_secrets_metadata_fixture_contains_no_secret_material", () => {
  assert.deepEqual(secretLeakFields(HUD_SECRET_FIXTURE), []);
  const markup = render(AccessSecretsView, {
    rows: [HUD_SECRET_FIXTURE],
    members: [{ id: 1, username: "op", role: "owner" }],
    memberDisabled: [{
      id: "member.retire",
      label: "Retire owner",
      reason: "The last Owner cannot be retired.",
    }],
  });
  const text = visibleText(markup);
  assert.doesNotMatch(text, /VAULT-TEST-PLAINTEXT/);
  assert.doesNotMatch(text, /wrapped_dek/);
  assert.doesNotMatch(text, /ciphertext/);
  assert.doesNotMatch(markup, /••••/);
  assert.match(text, /This kind is not exportable/);
  assert.match(text, /Members/);
  assert.match(text, /Roles/);
  assert.match(text, /Vault/);
  assert.match(text, /Sessions/);
  assert.match(text, /Security/);
  assert.match(text, /ADD SECRET/);
  assert.match(text, /ROTATE/);
  assert.match(text, /REVIEW ROTATION PLAN/);
  const members = visibleText(render(AccessSecretsView, {
    rows: [HUD_SECRET_FIXTURE],
    members: [{ id: 1, username: "op", role: "owner" }],
    memberDisabled: [{
      id: "member.retire",
      label: "Retire owner",
      reason: "The last Owner cannot be retired.",
    }],
    tab: "members",
  }));
  assert.match(members, /INVITE USER/);
  assert.match(members, /The last Owner cannot be retired/);
});

test("overview_cards_do_not_mutate_and_drill_by_label", () => {
  const markup = render(OverviewView, { data: HUD_OVERVIEW_FIXTURE, onNav: () => {} });
  const text = visibleText(markup);
  assert.match(text, /none of these cards mutate/);
  assert.match(text, /View attention queue/);
  assert.doesNotMatch(text, /Delete/);
  assert.doesNotMatch(markup, /<form/);
});
