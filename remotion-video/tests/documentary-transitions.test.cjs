const assert = require("node:assert/strict");
const test = require("node:test");

const {
  activeDocumentaryOverlay,
  buildDocumentarySequenceTimings,
  documentaryTransitionOpacity,
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

const assertAntonCrossoverSelection = (type, duration, crossoverOffset) => {
  const timings = buildDocumentarySequenceTimings(
    SEGMENTS,
    transitionScenes(type, duration),
    FPS,
  );
  const sceneEndFrame = 240;
  const firstCrossover = timings[1].startFrame + crossoverOffset;
  const secondCrossover = timings[2].startFrame + crossoverOffset;

  assert.deepEqual(timings.map((timing) => timing.startFrame), [0, 80, 160]);
  assert.equal(
    activeDocumentaryOverlay(firstCrossover - 1, timings, OVERLAYS, sceneEndFrame),
    OVERLAYS[0],
  );
  assert.equal(
    activeDocumentaryOverlay(firstCrossover, timings, OVERLAYS, sceneEndFrame),
    OVERLAYS[1],
  );
  assert.equal(
    activeDocumentaryOverlay(firstCrossover + 1, timings, OVERLAYS, sceneEndFrame),
    OVERLAYS[1],
  );
  assert.equal(
    activeDocumentaryOverlay(secondCrossover - 1, timings, OVERLAYS, sceneEndFrame),
    OVERLAYS[1],
  );
  assert.equal(
    activeDocumentaryOverlay(secondCrossover, timings, OVERLAYS, sceneEndFrame),
    OVERLAYS[2],
  );
  assert.equal(
    activeDocumentaryOverlay(secondCrossover + 1, timings, OVERLAYS, sceneEndFrame),
    OVERLAYS[2],
  );

  if (crossoverOffset > 0) {
    const transition = {type, duration};
    const outgoingDuration = timings[0].durationFrames;
    const outgoingBefore = documentaryTransitionOpacity(
      firstCrossover - 1,
      outgoingDuration,
      undefined,
      transition,
      FPS,
    );
    const incomingBefore = documentaryTransitionOpacity(
      crossoverOffset - 1,
      timings[1].durationFrames,
      transition,
      transition,
      FPS,
    );
    const outgoingAt = documentaryTransitionOpacity(
      firstCrossover,
      outgoingDuration,
      undefined,
      transition,
      FPS,
    );
    const incomingAt = documentaryTransitionOpacity(
      crossoverOffset,
      timings[1].durationFrames,
      transition,
      transition,
      FPS,
    );
    assert.ok(outgoingBefore > incomingBefore);
    assert.ok(incomingAt >= outgoingAt);
  }

  // Scene 1 has a one-second audio-tail buffer after the 9-second fixture.
  // The last grounded card remains the one global overlay through that tail.
  assert.equal(
    activeDocumentaryOverlay(239, timings, OVERLAYS, sceneEndFrame),
    OVERLAYS[2],
  );
  assert.equal(
    activeDocumentaryOverlay(240, timings, OVERLAYS, sceneEndFrame),
    undefined,
  );
};

test("hard-cut fixture selects exactly one card at both canonical boundaries", () => {
  assertAntonCrossoverSelection("cut", 0, 0);
});

test("0.4-second crossfade switches the global card at visual dominance", () => {
  assertAntonCrossoverSelection("crossfade", 0.4, 5);
});

for (const type of ["dissolve", "dip_to_black"]) {
  test(`1.5-second ${type} switches the global card at visual dominance`, () => {
    assertAntonCrossoverSelection(type, 1.5, 18);
  });
}

test("captionless legacy timings stay cardless at every frame", () => {
  const timings = buildDocumentarySequenceTimings(
    [{imageFile: "legacy.png", duration: 3}],
    [{transition_in: {type: "cut", duration: 0}}],
    FPS,
  );

  for (const frame of [0, 1, 71, 72, 239]) {
    assert.equal(activeDocumentaryOverlay(frame, timings, [undefined], 240), undefined);
  }
});

test("frames before the first canonical start have no overlay", () => {
  const timings = buildDocumentarySequenceTimings(
    SEGMENTS,
    transitionScenes("crossfade", 0.4),
    FPS,
  );
  assert.equal(activeDocumentaryOverlay(-1, timings, OVERLAYS, 240), undefined);
});
