const assert = require("node:assert/strict");
const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const test = require("node:test");

const {
  MOTION_AUDIO_FILES,
  MOTION_AUDIO_SHA256,
  PREVIEW_PRIMITIVES,
  SIGNAL_PULSE_CYCLE_SECONDS,
  CENTER_CROP_BOUNDS,
  SILENCE_DROP_WINDOW_SECONDS,
  activeWordIndex,
  assertLocalMotionSources,
  previewSegments,
  routeProgress,
  signalPulseBurstFrames,
  signalPulseCycleFrame,
  signalPulseEnergy,
  motionMixGains,
} = require("../.motion-test-build/contracts.js");

test("preview is nine contiguous four-second frame ranges", () => {
  const segments = previewSegments(24);
  assert.equal(segments.length, 9);
  assert.deepEqual(segments.map((item) => item.name), [...PREVIEW_PRIMITIVES]);
  assert.equal(segments[0].from, 0);
  assert.equal(segments.at(-1).from + segments.at(-1).durationInFrames, 864);
  segments.slice(1).forEach((item, index) => {
    assert.equal(item.from, segments[index].from + segments[index].durationInFrames);
  });
});

test("silence drop mutes every audible lane before a frame-driven pulse entry", () => {
  const fps = 24;
  const start = Math.round(SILENCE_DROP_WINDOW_SECONDS.start * fps);
  const end = Math.round(SILENCE_DROP_WINDOW_SECONDS.end * fps);
  for (let frame = start; frame < end; frame++) {
    assert.deepEqual(motionMixGains(frame, fps), {
      bed: 0,
      silenceCue: 0,
      pulse: 0,
      clicks: 0,
      transition: 0,
    });
  }
  assert.equal(motionMixGains(start - 1, fps).bed, 1);
  assert.equal(motionMixGains(start - 1, fps).silenceCue, 1);
  assert.ok(motionMixGains(end + 4, fps).pulse > 0);
  assert.ok(motionMixGains(end + 4, fps).bed > 0);
  const source = fs.readFileSync(path.join(__dirname, "..", "src", "motion-library", "MotionAudioSystem.tsx"), "utf8");
  assert.match(source, /silence-drop\.wav/);
  assert.match(source, /premountFor=\{fps\}/);
});

test("critical content contract fits the centered 9:16 crop", () => {
  assert.deepEqual(CENTER_CROP_BOUNDS, {
    x: 656,
    width: 608,
    criticalX: 680,
    criticalWidth: 560,
    criticalTop: 120,
    criticalBottom: 930,
  });
  assert.ok(CENTER_CROP_BOUNDS.criticalX >= CENTER_CROP_BOUNDS.x);
  assert.ok(CENTER_CROP_BOUNDS.criticalX + CENTER_CROP_BOUNDS.criticalWidth <= CENTER_CROP_BOUNDS.x + CENTER_CROP_BOUNDS.width);
  const source = fs.readFileSync(path.join(__dirname, "..", "src", "motion-library", "CropSafe.tsx"), "utf8");
  assert.match(source, /data-crop-safe="critical-9x16"/);
});

test("signal motif is a phase-locked 11-second seven-burst cycle", () => {
  const fps = 24;
  const cycleFrames = SIGNAL_PULSE_CYCLE_SECONDS * fps;
  assert.equal(cycleFrames, 264);
  assert.deepEqual(signalPulseBurstFrames(fps), [0, 8, 16, 54, 63, 127, 204]);
  assert.equal(signalPulseCycleFrame(0, fps), 0);
  assert.equal(signalPulseCycleFrame(264, fps), 0);
  assert.equal(signalPulseCycleFrame(-1, fps), 263);
  for (let frame = 0; frame < cycleFrames; frame += 7) {
    assert.equal(signalPulseEnergy(frame, fps), signalPulseEnergy(frame + cycleFrames, fps));
  }
  const bursts = signalPulseBurstFrames(fps);
  assert.deepEqual(
    bursts.slice(1).map((value, index) => value - bursts[index]),
    [8, 8, 38, 9, 64, 77],
  );
});

test("measured Unicode words use half-open frame timing", () => {
  const words = [
    {text: "todavía", startFrame: 10, endFrame: 20},
    {text: "respira", startFrame: 20, endFrame: 30},
  ];
  assert.equal(activeWordIndex(words, 9), -1);
  assert.equal(activeWordIndex(words, 10), 0);
  assert.equal(activeWordIndex(words, 20), 1);
  assert.equal(activeWordIndex(words, 30), -1);
});

test("route progress is deterministic, clamped, and validates duration", () => {
  assert.equal(routeProgress(-1, 0, 10), 0);
  assert.equal(routeProgress(5, 0, 10), 0.5);
  assert.equal(routeProgress(20, 0, 10), 1);
  assert.throws(() => routeProgress(0, 0, 0), /positive/);
});

test("motion sources reject remote, traversal, and token-dependent assets", () => {
  assert.doesNotThrow(() => assertLocalMotionSources(["motion-audio/music-bed.wav", "images/evidence.webp"]));
  for (const source of ["https://cdn.test/a.png", "../secret", "mapbox://styles/demo", "map?access_token=x"]) {
    assert.throws(() => assertLocalMotionSources([source]), /deterministic local/);
  }
});

test("all generated WAV fixtures are tracked-format local PCM assets", () => {
  assert.deepEqual(MOTION_AUDIO_FILES, [
    "signal-pulse.wav",
    "silence-drop.wav",
    "data-click.wav",
    "transition-envelope.wav",
    "music-bed.wav",
  ]);
  for (const file of MOTION_AUDIO_FILES) {
    const bytes = fs.readFileSync(path.join(__dirname, "..", "public", "motion-audio", file));
    assert.equal(bytes.subarray(0, 4).toString("ascii"), "RIFF");
    assert.equal(bytes.subarray(8, 12).toString("ascii"), "WAVE");
    assert.ok(bytes.length > 1000);
    assert.equal(crypto.createHash("sha256").update(bytes).digest("hex"), MOTION_AUDIO_SHA256[file]);
  }
});

test("open font is exact-version pinned and license documented", () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
  assert.equal(pkg.dependencies["@fontsource/noto-sans"], "5.2.5");
  const provenance = fs.readFileSync(path.join(__dirname, "..", "OPEN_SOURCE_ASSETS.md"), "utf8");
  assert.match(provenance, /SIL Open Font License 1\.1/);
});
