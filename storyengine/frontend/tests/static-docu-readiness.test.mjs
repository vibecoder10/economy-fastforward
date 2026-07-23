import assert from "node:assert/strict";
import test from "node:test";
import {
  getStaticDocuReadiness,
  parseStaticDocuCaption,
  staticDocuViewLabel,
} from "../src/lib/static-docu.ts";

const caption = (overrides = {}) => JSON.stringify({
  title: "B-52 Stratofortress",
  sub: "USAF • 1955–present",
  specs: ["Wingspan 185 ft"],
  target_views: 3,
  minimum_views: 2,
  ...overrides,
});

const asset = (scene, imageIndex, status, overrides = {}) => ({
  scene,
  image_index: imageIndex,
  image_url: status === "done" ? `view-${scene}-${imageIndex}.png` : null,
  status,
  generation_method: "static_docu",
  caption: caption(),
  ...overrides,
});

test("a new aircraft is ready with two verified views when the third fails", () => {
  const readiness = getStaticDocuReadiness([
    asset(1, 1, "done"),
    asset(1, 2, "done"),
    asset(1, 3, "qa_rejected"),
  ], [1]);

  assert.equal(readiness.allReady, true);
  assert.equal(readiness.readyUnits, 1);
  assert.equal(readiness.readyViews, 2);
  assert.equal(readiness.units[0].targetViews, 3);
  assert.equal(readiness.units[0].minimumViews, 2);
});

test("one verified view is blocked and cannot make the aircraft render-ready", () => {
  const readiness = getStaticDocuReadiness([
    asset(1, 1, "done"),
    asset(1, 2, "qa_rejected"),
    asset(1, 3, "qa_rejected"),
  ], [1]);

  assert.equal(readiness.allReady, false);
  assert.equal(readiness.blockedUnits, 1);
  assert.equal(readiness.units[0].status, "blocked");
});

test("legacy one-image aircraft remain ready without a multi-view caption", () => {
  const readiness = getStaticDocuReadiness([
    asset(7, 1, "done", { caption: null, generation_method: null }),
  ], [7]);

  assert.equal(readiness.allReady, true);
  assert.equal(readiness.units[0].minimumViews, 1);
});

test("caption parsing and view labels are defensive", () => {
  assert.equal(parseStaticDocuCaption("not-json"), null);
  const parsed = parseStaticDocuCaption(caption({ view_role: "top_oblique" }));
  assert.equal(staticDocuViewLabel(parsed, 2), "Top-oblique");
});
