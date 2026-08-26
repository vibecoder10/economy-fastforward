const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildDocumentarySequenceTimings,
  documentaryTransitionOpacity,
} = require("../.documentary-test-build/documentaryTransitions.js");

const FPS = 24;
const SEGMENTS = [
  {imageFile: "left.png", duration: 3},
  {imageFile: "right.png", duration: 3},
];

const transitionScenes = (type, duration) => [
  {
    overlay: {position: "bottom_left"},
    transition_in: {type: "fade_from_black", duration: 1},
    transition_out: {type, duration},
  },
  {
    overlay: {position: "bottom_right"},
    transition_in: {type, duration},
    transition_out: {type: "fade_to_black", duration: 1},
  },
];

const activeCards = (globalFrame, timings, scenes) => timings
  .map((timing, index) => ({timing, scene: scenes[index]}))
  .filter(({timing}) => (
    globalFrame >= timing.startFrame
    && globalFrame < timing.startFrame + timing.durationFrames
  ))
  .map(({timing, scene}) => ({
    position: scene.overlay.position,
    opacity: documentaryTransitionOpacity(
      globalFrame - timing.startFrame,
      timing.durationFrames,
      scene.transition_in,
      scene.transition_out,
      FPS,
    ),
  }));

test("hard cut swaps opposite-side cards without a shared frame", () => {
  const scenes = transitionScenes("cut", 0);
  const timings = buildDocumentarySequenceTimings(SEGMENTS, scenes, FPS);

  assert.deepEqual(timings.map(({startFrame, durationFrames}) => ({
    startFrame,
    durationFrames,
  })), [
    {startFrame: 0, durationFrames: 72},
    {startFrame: 72, durationFrames: 72},
  ]);
  assert.deepEqual(activeCards(71, timings, scenes), [
    {position: "bottom_left", opacity: 1},
  ]);
  assert.deepEqual(activeCards(72, timings, scenes), [
    {position: "bottom_right", opacity: 1},
  ]);
});

test("standard crossfade keeps card opacities complementary through its overlap", () => {
  const scenes = transitionScenes("crossfade", 0.4);
  const timings = buildDocumentarySequenceTimings(SEGMENTS, scenes, FPS);
  const overlapFrames = Math.floor(0.4 * FPS);

  assert.equal(timings[0].durationFrames, 72 + overlapFrames);
  for (let offset = 0; offset < overlapFrames; offset += 1) {
    const cards = activeCards(72 + offset, timings, scenes);
    assert.equal(cards.length, 2);
    assert.ok(Math.abs(cards[0].opacity + cards[1].opacity - 1) < 1e-9);
  }
});

for (const type of ["dissolve", "dip_to_black"]) {
  test(`${type} keeps both Sequence lifetimes and never blanks the card`, () => {
    const scenes = transitionScenes(type, 1.5);
    const timings = buildDocumentarySequenceTimings(SEGMENTS, scenes, FPS);
    const overlapFrames = Math.floor(1.5 * FPS);

    assert.equal(timings[0].durationFrames, 72 + overlapFrames);
    for (let offset = 0; offset < overlapFrames; offset += 1) {
      const cards = activeCards(72 + offset, timings, scenes);
      assert.equal(cards.length, 2);
      assert.ok(Math.abs(cards[0].opacity + cards[1].opacity - 1) < 1e-9);
      assert.ok(Math.max(cards[0].opacity, cards[1].opacity) >= 0.5);
    }
    assert.ok(activeCards(72 + overlapFrames - 1, timings, scenes)[0].opacity > 0);
  });
}
