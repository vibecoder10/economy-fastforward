const assert = require("node:assert/strict");
const test = require("node:test");

const {
  activeDocumentaryOverlay,
  buildDocumentarySequenceTimings,
} = require("../.documentary-test-build/documentaryTransitions.js");

const FPS = 24;
// The real Anton Scene is 9 seconds of narration plus Main's existing
// one-second scene-tail buffer. Scene's transcript-free fallback divides
// those 10 seconds evenly across its three images.
const ANTON_VIEW_SECONDS = 10 / 3;
const SEGMENTS = [
  {imageFile: "identity.png", duration: ANTON_VIEW_SECONDS},
  {imageFile: "spec.png", duration: ANTON_VIEW_SECONDS},
  {imageFile: "script.png", duration: ANTON_VIEW_SECONDS},
];
const OVERLAYS = [
  {kind: "identity", title: "B-52", body: "USAF", position: "bottom_left"},
  {kind: "spec", title: "KEY SPEC", body: "185 ft", position: "bottom_right"},
  {kind: "script", title: "B-52", body: "Exact closing line.", position: "bottom_left"},
];

const transitionScenes = (type, duration) => [
  {
    transition_in: {type: "fade_from_black", duration: 1},
    transition_out: {type, duration},
  },
  {
    transition_in: {type, duration},
    transition_out: {type, duration},
  },
  {
    transition_in: {type, duration},
    transition_out: {type: "fade_to_black", duration: 1},
  },
];

const assertAntonBoundarySelection = (type, duration) => {
  const timings = buildDocumentarySequenceTimings(
    SEGMENTS,
    transitionScenes(type, duration),
    FPS,
  );

  assert.deepEqual(timings.map((timing) => timing.startFrame), [0, 80, 160]);
  assert.equal(activeDocumentaryOverlay(79, timings, OVERLAYS), OVERLAYS[0]);
  assert.equal(activeDocumentaryOverlay(80, timings, OVERLAYS), OVERLAYS[1]);
  assert.equal(activeDocumentaryOverlay(81, timings, OVERLAYS), OVERLAYS[1]);
  assert.equal(activeDocumentaryOverlay(159, timings, OVERLAYS), OVERLAYS[1]);
  assert.equal(activeDocumentaryOverlay(160, timings, OVERLAYS), OVERLAYS[2]);
  assert.equal(activeDocumentaryOverlay(161, timings, OVERLAYS), OVERLAYS[2]);

  // Scene 1 has a one-second audio-tail buffer after the 9-second fixture.
  // The last grounded card remains the one global overlay through that tail.
  assert.equal(activeDocumentaryOverlay(239, timings, OVERLAYS), OVERLAYS[2]);
};

test("hard-cut fixture selects exactly one card at both canonical boundaries", () => {
  assertAntonBoundarySelection("cut", 0);
});

test("0.4-second crossfade cannot change global card boundary selection", () => {
  assertAntonBoundarySelection("crossfade", 0.4);
});

for (const type of ["dissolve", "dip_to_black"]) {
  test(`1.5-second ${type} cannot extend or overlap global card lifetime`, () => {
    assertAntonBoundarySelection(type, 1.5);
  });
}

test("captionless legacy timings stay cardless at every frame", () => {
  const timings = buildDocumentarySequenceTimings(
    [{imageFile: "legacy.png", duration: 3}],
    [{transition_in: {type: "cut", duration: 0}}],
    FPS,
  );

  for (const frame of [0, 1, 71, 72, 239]) {
    assert.equal(activeDocumentaryOverlay(frame, timings, [undefined]), undefined);
  }
});

test("frames before the first canonical start have no overlay", () => {
  const timings = buildDocumentarySequenceTimings(
    SEGMENTS,
    transitionScenes("crossfade", 0.4),
    FPS,
  );
  assert.equal(activeDocumentaryOverlay(-1, timings, OVERLAYS), undefined);
});
