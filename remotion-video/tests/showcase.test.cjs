const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  STAGED_PROOF_SOURCE_KEYS,
  STORYENGINE_SHOWCASE_DEFAULT_PROPS,
  STORYENGINE_SHOWCASE_SOURCE_CLIP_PROOF_PROPS,
  STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS,
} = require("../.showcase-test-build/showcase/fixture.js");
const {
  SHOWCASE_CUES,
  SHOWCASE_MANIFEST_VERSION,
  SHOWCASE_QUOTE,
  SHOWCASE_REQUEST,
  compileShowcaseManifest,
  resolveShowcaseMediaSlots,
  stagedLocalPathForSourceKey,
  validateStoryEngineShowcaseProps,
} = require("../.showcase-test-build/showcase/manifest.js");
const {
  MARA_MEASURED_WORDS,
  MARA_RESPONSE_WORDS,
  SHOWCASE_AUDIO_CUES,
  SHOWCASE_PULSE_ANCHOR_FRAME,
  approvedCaptionOpacity,
  approvedMediaOpacity,
  showcasePulseFrame,
  showcaseBedGain,
} = require("../.showcase-test-build/showcase/timing.js");
const {signalPulseCycleFrame} = require("../.showcase-test-build/motion-library/contracts.js");
const {canonicalJson, sha256Hex} = require("../.showcase-test-build/custom-film/canonical.js");

const rehashProps = (value) => {
  const {props_hash: _oldHash, ...body} = value;
  value.props_hash = sha256Hex(canonicalJson(body));
  return value;
};

test("approved props lock exactly 300 seconds, 7200 frames, and four role boundaries", () => {
  const props = validateStoryEngineShowcaseProps(STORYENGINE_SHOWCASE_DEFAULT_PROPS);
  assert.deepEqual(props.video, {fps: 24, width: 1920, height: 1080, total_duration_seconds: 300, total_frames: 7200});
  assert.deepEqual(props.sections.map(({role,start_frame,duration_frames}) => ({role,start_frame,duration_frames})), [
    {role: "opening", start_frame: 0, duration_frames: 1080},
    {role: "evidence", start_frame: 1080, duration_frames: 2520},
    {role: "case_study", start_frame: 3600, duration_frames: 2160},
    {role: "explanation", start_frame: 5760, duration_frames: 1440},
  ]);
  for (const section of props.sections) {
    assert.equal(section.transition_in.overlap_frames, 0);
    assert.equal(section.transition_out.overlap_frames, 0);
    assert.equal(section.transition_in.accounting, "inside_section");
    assert.equal(section.transition_out.accounting, "inside_section");
  }
});

test("versioned cue compiler fills every inclusive frame exactly once", () => {
  const manifest = compileShowcaseManifest(STORYENGINE_SHOWCASE_DEFAULT_PROPS);
  assert.equal(manifest.schema_version, SHOWCASE_MANIFEST_VERSION);
  assert.equal(manifest.motion_plan_version, "storyengine-showcase-motion-plan-v1");
  assert.equal(manifest.cues.length, 34);
  const primitives = new Set([
    ...manifest.motion_plan.global_primitives,
    ...manifest.cues.map((cue) => cue.primitive),
  ]);
  for (const primitive of [
    "SignalPulse",
    "OutageMap",
    "EvidenceBoard",
    "IncidentTimeline",
    "RadioWaveform",
    "BilingualCaptions",
    "NetworkExplainer",
    "StoryEngineReveal",
    "MotionAudioSystem",
  ]) {
    assert.equal(primitives.has(primitive), true, `${primitive} is not scheduled`);
  }
  let frame = 0;
  for (const cue of manifest.cues) {
    assert.equal(cue.from, frame);
    assert.equal(cue.durationInFrames, cue.to - cue.from + 1);
    const section = STORYENGINE_SHOWCASE_DEFAULT_PROPS.sections[cue.sectionIndex];
    assert.ok(cue.from >= section.start_frame);
    assert.ok(cue.to < section.start_frame + section.duration_frames);
    frame = cue.to + 1;
  }
  assert.equal(frame, 7200);
});

test("all authored Sequences premount and pulse receives the global timeline frame", () => {
  for (const file of ["StoryEngineCustomFilmShowcase.tsx", "ShowcaseAudio.tsx", "ApprovedMedia.tsx"]) {
    const source = fs.readFileSync(path.join(__dirname, "..", "src", "showcase", file), "utf8");
    const sequenceCount = (source.match(/<Sequence\b/g) || []).length;
    const premountCount = (source.match(/premountFor=/g) || []).length;
    assert.equal(premountCount, sequenceCount, `${file} has an unpremounted Sequence`);
  }
  const composition = fs.readFileSync(path.join(__dirname, "..", "src", "showcase", "StoryEngineCustomFilmShowcase.tsx"), "utf8");
  assert.match(composition, /MotionTimelineProvider value=\{showcasePulseFrame\(absoluteFrame\)\}/);
  assert.equal(SHOWCASE_PULSE_ANCHOR_FRAME, 444);
  for (const frame of [444, 708, 972]) {
    assert.equal(signalPulseCycleFrame(showcasePulseFrame(frame), 24), 0);
  }
  const scene = fs.readFileSync(path.join(__dirname, "..", "src", "showcase", "ShowcaseScene.tsx"), "utf8");
  assert.match(scene, /signalPulseEnergy\(pulseFrame, 24\)/);
  assert.match(scene, /data-title-pulse-energy/);
  assert.match(scene, /switch \(cue\.primitive\)/);
  assert.match(scene, /Unsupported StoryEngine motion cue/);
  assert.match(scene, /titleStyle=\{\{opacity: absoluteFrame >= 7080 \? 0 : 1\}\}/);
});

test("showcase scene source preserves exact historical, recovery, and lane labels", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "src", "showcase", "ShowcaseScene.tsx"), "utf8");
  for (const label of ["1998", "BLACKOUT DRILL", "2012", "STORM FAILURE", "CURRENT OUTAGE"]) assert.match(source, new RegExp(label));
  for (const label of ["HOSPITAL", "TRANSIT", "EMERGENCY LINES", "PUBLIC SCREENS"]) assert.match(source, new RegExp(label));
  for (const label of ["MAP", "EVIDENCE", "CAPTIONS", "AUDIO", "MOTION"]) assert.match(source, new RegExp(`\"${label}\"`));
});

test("motion-card titles stay centered inside the title-safe boundary", () => {
  const primitiveFrame = fs.readFileSync(path.join(__dirname, "..", "src", "motion-library", "PrimitiveFrame.tsx"), "utf8");
  assert.match(primitiveFrame, /bottom: 190/);
  assert.match(primitiveFrame, /textAlign: "center"/);
  const media = fs.readFileSync(path.join(__dirname, "..", "src", "showcase", "ApprovedMedia.tsx"), "utf8");
  assert.match(media, /top: 760/);
});

test("measured bilingual timings are Unicode-safe, ordered, irregular, and cue-bound", () => {
  for (const [words, start, end] of [
    [MARA_MEASURED_WORDS, 3840, 4199],
    [MARA_RESPONSE_WORDS, 4440, 4919],
  ]) {
    assert.ok(words[0].startFrame >= start);
    assert.ok(words.at(-1).endFrame <= end);
    words.slice(1).forEach((word, index) => assert.equal(word.startFrame, words[index].endFrame));
    assert.ok(new Set(words.map((word) => word.endFrame - word.startFrame)).size > 3);
  }
  assert.equal(MARA_MEASURED_WORDS.map((word) => word.text).join(" "), "Mara, si puedes oírme, no reinicies la red.");
});

test("approved media supports motion graphics and clears the persuasive reveal", () => {
  assert.equal(approvedMediaOpacity("case_study", 3700), 0.62);
  assert.equal(approvedMediaOpacity("case_study", 3900), 0.16);
  assert.equal(approvedMediaOpacity("evidence", 2400), 0.14);
  assert.equal(approvedMediaOpacity("explanation", 6623), 0.12);
  assert.equal(approvedMediaOpacity("explanation", 6624), 0);
  assert.equal(approvedCaptionOpacity("case_study", 3900), 0);
  assert.equal(approvedCaptionOpacity("case_study", 4300), 1);
  assert.equal(approvedCaptionOpacity("explanation", 6624), 0);
});

test("identity, media, approval, and hash tampering is rejected", () => {
  const mutate = (change) => {
    const value = structuredClone(STORYENGINE_SHOWCASE_DEFAULT_PROPS);
    change(value);
    return value;
  };
  assert.throws(() => validateStoryEngineShowcaseProps(mutate((value) => { value.identity.plan_hash = "9".repeat(64); })), /hash changed/);
  assert.throws(() => validateStoryEngineShowcaseProps(mutate((value) => { value.identity.max_spend = 16; })), /hash changed/);
  assert.throws(() => validateStoryEngineShowcaseProps(mutate((value) => { value.sections[2].assets[0].source_key = "other"; })), /hash changed/);
  assert.throws(() => validateStoryEngineShowcaseProps(mutate((value) => { value.sections[2].captions[0].text = "changed"; })), /hash changed/);
});

test("assembly v3 requires renderer contract and bundle identity while v2 remains valid", () => {
  const v3 = structuredClone(STORYENGINE_SHOWCASE_DEFAULT_PROPS);
  v3.identity.assembly_version = "custom-film-assembly-v3";
  v3.identity.renderer_contract_version = "custom-film-remotion-renderer-v1";
  v3.identity.renderer_bundle_hash = "c".repeat(64);
  const {props_hash: _oldHash, ...v3Body} = v3;
  v3.props_hash = sha256Hex(canonicalJson(v3Body));
  assert.doesNotThrow(() => validateStoryEngineShowcaseProps(v3));

  const missing = structuredClone(v3);
  delete missing.identity.renderer_bundle_hash;
  const {props_hash: _missingHash, ...missingBody} = missing;
  missing.props_hash = sha256Hex(canonicalJson(missingBody));
  assert.throws(() => validateStoryEngineShowcaseProps(missing), /renderer identity/);
  assert.doesNotThrow(() => validateStoryEngineShowcaseProps(STORYENGINE_SHOWCASE_DEFAULT_PROPS));
});

test("source-key media slots allow local visual replacement and reject remote paths", () => {
  const visualKey = STAGED_PROOF_SOURCE_KEYS.video;
  const exactPath = stagedLocalPathForSourceKey(visualKey, "video");
  const slots = resolveShowcaseMediaSlots(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS, {
    [visualKey]: {localPath: exactPath},
  });
  assert.ok(slots.some((slot) =>
    slot.kind === "visual" &&
    slot.sourceKey === visualKey &&
    slot.mediaType === "video" &&
    slot.localPath === exactPath &&
    slot.sectionId === "showcase-opening" &&
    slot.sectionOrder === 0 &&
    slot.startFrame === 60 &&
    slot.durationInFrames === 1020 &&
    slot.timingMode === "repeat_then_trim"
  ));
  for (const [field, value] of [
    ["sourceKey", "wrong"],
    ["role", "wrong"],
    ["mediaType", "image"],
    ["sectionId", "wrong"],
    ["startFrame", 61],
    ["timingMode", "static_hold"],
  ]) {
    assert.throws(() => resolveShowcaseMediaSlots(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS, {
      [visualKey]: {localPath: exactPath, [field]: value},
    }), /only supply localPath/);
  }
  assert.throws(() => resolveShowcaseMediaSlots(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS, {
    [visualKey]: {localPath: "https://cdn.test/opening.mp4"},
  }), /path or media type changed/);
  assert.throws(() => resolveShowcaseMediaSlots(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS, {
    "unapproved:key": {localPath: "custom-film-sources/video/no.mp4"},
  }), /not approved/);
  assert.equal(stagedLocalPathForSourceKey("approved:asset:42", "video"), stagedLocalPathForSourceKey("approved:asset:42", "video"));
  assert.match(stagedLocalPathForSourceKey("approved:asset:42", "video"), /^custom-film-sources\/video\/[0-9a-f]{64}\.mp4$/);
});

test("composition consumes approved visual, audio, and caption slots", () => {
  const stagedSlots = resolveShowcaseMediaSlots(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS);
  assert.equal(stagedSlots.filter((slot) => slot.kind === "visual").length, 2);
  assert.equal(stagedSlots.filter((slot) => slot.kind === "audio" && !slot.sourceKey.startsWith("synthetic:")).length, 1);
  const composition = fs.readFileSync(path.join(__dirname, "..", "src", "showcase", "StoryEngineCustomFilmShowcase.tsx"), "utf8");
  assert.match(composition, /ApprovedMediaLayer slots=\{manifest\.media_slots\}/);
  assert.match(composition, /ApprovedCaptionLayer sections=\{input\.sections\}/);
  const mediaSource = fs.readFileSync(path.join(__dirname, "..", "src", "showcase", "ApprovedMedia.tsx"), "utf8");
  for (const token of ["<Img", "<OffthreadVideo", "<Audio", "caption.text", "data-approved-source-key"]) assert.match(mediaSource, new RegExp(token.replace("<", "\\<")));

  for (const slot of stagedSlots) {
    if (slot.kind === "procedural" || slot.sourceKey.startsWith("synthetic:")) continue;
    const bytes = fs.readFileSync(path.join(__dirname, "..", "public", slot.localPath));
    assert.equal(crypto.createHash("sha256").update(bytes).digest("hex"), slot.sourceSha256);
  }
  assert.equal(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS.sections[0].captions[0].text, "STAGED CAPTION · APPROVED LOCAL SOURCE");
});

test("approved narration sources concatenate in order with exact playback transform and bounds", () => {
  const props = structuredClone(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS);
  props.sections[0].audio.sources = [
    {source_key: "approved:narration:0", source_sha256: "1".repeat(64), source_duration_ms: 15000},
    {source_key: "approved:narration:1", source_sha256: "2".repeat(64), source_duration_ms: 21000},
  ];
  props.sections[0].audio.timing_transform = {
    mode: "atempo",
    source_duration_ms: 36000,
    output_duration_ms: 45000,
    atempo_chain: [0.8],
    caption_scale: 1.25,
  };
  rehashProps(props);
  const slots = resolveShowcaseMediaSlots(props)
    .filter((slot) => slot.kind === "audio" && slot.sectionId === "showcase-opening");
  assert.deepEqual(
    slots.map(({sourceIndex,startFrame,durationInFrames,sourceDurationMs,playbackRate,endBehavior}) => ({
      sourceIndex,startFrame,durationInFrames,sourceDurationMs,playbackRate,endBehavior,
    })),
    [
      {sourceIndex: 0, startFrame: 0, durationInFrames: 450, sourceDurationMs: 15000, playbackRate: 0.8, endBehavior: "trim_or_silence_pad"},
      {sourceIndex: 1, startFrame: 450, durationInFrames: 630, sourceDurationMs: 21000, playbackRate: 0.8, endBehavior: "trim_or_silence_pad"},
    ],
  );
  assert.equal(slots[0].startFrame + slots[0].durationInFrames, slots[1].startFrame);
  assert.equal(slots[1].startFrame + slots[1].durationInFrames, 1080);
});

test("source_clip uses only approved video audio while voice_over video stays muted", () => {
  const sourceClipSlots = resolveShowcaseMediaSlots(STORYENGINE_SHOWCASE_SOURCE_CLIP_PROOF_PROPS);
  const openingSlots = sourceClipSlots.filter((slot) => slot.sectionId === "showcase-opening");
  assert.equal(openingSlots.filter((slot) => slot.kind === "audio").length, 0);
  const sourceVideo = openingSlots.find((slot) => slot.kind === "visual" && slot.mediaType === "video");
  assert.ok(sourceVideo);
  assert.equal(sourceVideo.nativeAudioEnabled, true);
  assert.equal(sourceVideo.nativeAudioGainDb, -3);
  assert.equal(sourceVideo.nativeAudioPlaybackRate, 1);

  const voiceOverSlots = resolveShowcaseMediaSlots(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS);
  assert.equal(
    voiceOverSlots.find((slot) => slot.kind === "visual" && slot.mediaType === "video").nativeAudioEnabled,
    false,
  );
  assert.equal(
    voiceOverSlots.filter((slot) => slot.kind === "audio" && slot.sectionId === "showcase-opening").length,
    1,
  );
  const mediaSource = fs.readFileSync(path.join(__dirname, "..", "src", "showcase", "ApprovedMedia.tsx"), "utf8");
  assert.match(mediaSource, /muted=\{!slot\.nativeAudioEnabled\}/);
  assert.match(mediaSource, /playbackRate=\{slot\.nativeAudioPlaybackRate\}/);
  assert.match(mediaSource, /playbackRate=\{slot\.playbackRate\}/);
});

test("invalid or inconsistent approved audio timing fails closed", () => {
  const invalid = (change, pattern) => {
    const props = structuredClone(STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS);
    change(props.sections[0]);
    rehashProps(props);
    assert.throws(() => resolveShowcaseMediaSlots(props), pattern);
  };
  invalid(
    (section) => { section.audio.sources[0].source_duration_ms = 44000; },
    /source timing is incomplete/,
  );
  invalid(
    (section) => { section.audio.timing_transform.output_duration_ms = 44999; },
    /output duration changed/,
  );
  invalid(
    (section) => {
      section.audio.timing_transform = {
        mode: "atempo",
        source_duration_ms: 45000,
        output_duration_ms: 45000,
        atempo_chain: [1.1],
        caption_scale: 1,
      };
    },
    /timing transform is inconsistent/,
  );
  invalid(
    (section) => {
      section.audio.mode = "source_clip";
      section.audio.timing_transform.mode = "source_clip";
    },
    /must come only from approved video/,
  );
  invalid(
    (section) => {
      section.audio.mode = "source_clip";
      section.audio.sources = [];
      section.audio.timing_transform.mode = "source_clip";
      section.assets = [STORYENGINE_SHOWCASE_DEFAULT_PROPS.sections[0].assets[0]];
    },
    /contiguous approved video only/,
  );
});

test("source_clip requires exact all-video coverage and mode-transform coupling", () => {
  assert.doesNotThrow(() =>
    resolveShowcaseMediaSlots(STORYENGINE_SHOWCASE_SOURCE_CLIP_PROOF_PROPS),
  );

  const rejects = (base, change, pattern) => {
    const props = structuredClone(base);
    change(props.sections[0]);
    rehashProps(props);
    assert.throws(() => resolveShowcaseMediaSlots(props), pattern);
  };
  rejects(
    STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS,
    (section) => {
      section.audio.mode = "source_clip";
      section.audio.sources = [];
      section.audio.timing_transform.mode = "source_clip";
    },
    /contiguous approved video only/,
  );
  rejects(
    STORYENGINE_SHOWCASE_DEFAULT_PROPS,
    (section) => {
      section.audio.mode = "source_clip";
      section.audio.sources = [];
      section.audio.timing_transform.mode = "source_clip";
    },
    /contiguous approved video only/,
  );
  rejects(
    STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS,
    (section) => {
      section.audio.timing_transform.mode = "source_clip";
    },
    /mode and timing transform disagree/,
  );
  rejects(
    STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS,
    (section) => {
      section.audio.mode = "source_clip";
      section.audio.sources = [];
    },
    /mode and timing transform disagree/,
  );
});

test("quote is exact and manifest hides provider/model implementation fields", () => {
  const manifest = compileShowcaseManifest(STORYENGINE_SHOWCASE_DEFAULT_PROPS);
  assert.deepEqual(SHOWCASE_QUOTE, {estimate: 5.57, hard_cap: 15, approval_required: true});
  assert.match(SHOWCASE_REQUEST, /five-minute Custom Film/);
  assert.equal(manifest.props_hash, STORYENGINE_SHOWCASE_DEFAULT_PROPS.props_hash);
  assert.deepEqual(manifest.identity, STORYENGINE_SHOWCASE_DEFAULT_PROPS.identity);
  const keys = [];
  const visit = (value) => {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      keys.push(key);
      visit(child);
    }
  };
  visit(manifest);
  assert.equal(keys.some((key) => /provider|model/i.test(key)), false);
});

test("audio law preserves hard silence and exact section-bound hits", () => {
  for (let frame = 384; frame <= 443; frame++) assert.equal(showcaseBedGain(frame), 0);
  assert.ok(showcaseBedGain(383) > 0);
  assert.ok(showcaseBedGain(444) > 0);
  for (const cue of SHOWCASE_AUDIO_CUES) {
    const section = STORYENGINE_SHOWCASE_DEFAULT_PROPS.sections.find((item) => item.role === cue.role);
    assert.ok(cue.from >= section.start_frame);
    assert.ok(cue.to < section.start_frame + section.duration_frames);
    assert.equal(SHOWCASE_CUES.some((visual) => cue.from >= visual.from && cue.from <= visual.to), true);
  }
  assert.deepEqual(
    SHOWCASE_AUDIO_CUES.filter((cue) => cue.id.startsWith("reconnect-")).map((cue) => cue.from),
    [6048, 6132, 6216, 6300],
  );
  assert.deepEqual(
    SHOWCASE_AUDIO_CUES.filter((cue) => cue.id.includes("boundary")).map((cue) => [cue.from, cue.to]),
    [[1068,1079],[1080,1091],[3588,3599],[3600,3611],[5748,5759],[5760,5771]],
  );
});
