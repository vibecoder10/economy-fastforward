const assert = require("node:assert/strict");
const {createHash} = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  REMOTION_PROPS_VERSION,
  validateCustomFilmRemotionProps,
} = require("../.test-build/schema.js");
const {
  assertExactFrameLayout,
  secondsToFrames,
} = require("../.test-build/frameMath.js");
const {
  canonicalJson,
  sha256Hex,
} = require("../.test-build/canonical.js");
const pythonFixture = require("../test-fixtures/custom-film-remotion-props-v1.json");
const unicodeParity = require("../test-fixtures/canonical-unicode-parity.json");
const controlManifest = require("../src/custom-film/scene-control-proof-control-manifest.json");
const {
  validateDirectorRemotionProps,
} = require("../.test-build/directorSchema.js");
const {
  DIRECTOR_FILM_DEFAULT_PROPS,
} = require("../.test-build/directorFixture.js");
const {
  DIRECTOR_SCENE_CONTROL_LOCKS,
  DIRECTOR_SCENE_CONTROL_PROOF_PROPS,
} = require("../.test-build/directorSceneControlFixture.js");

const hash = (character) => character.repeat(64);

const fixture = () => ({
  schema_version: REMOTION_PROPS_VERSION,
  identity: {
    assembly_version: "custom-film-assembly-v1",
    assembly_manifest_hash: hash("1"),
    tenant_id: "tenant-1",
    video_id: "video-1",
    plan_id: "plan-1",
    plan_hash: hash("2"),
    quote_inputs_hash: hash("3"),
    approval_hash: hash("4"),
    runtime_hash: hash("5"),
    runtime_job_id: `custom-film-runtime:${hash("5")}`,
    max_spend: 15,
    render_engine: "remotion",
  },
  video: {
    fps: 24,
    width: 1920,
    height: 1080,
    total_duration_seconds: 1,
    total_frames: 24,
  },
  transition_accounting: {
    type: "dip_to_black_non_overlap",
    duration_source: "min(half_second, quarter_section)",
    overlap_frames_total: 0,
    duration_lives_inside_assigned_sections: true,
  },
  sections: [
    {
      section_id: "section-1",
      order_index: 0,
      role: "opening",
      render_mode: "static_docu",
      visual_profile: "photo_documentary",
      dialogue_audio: "voice_over",
      scene_ids: ["scene-1"],
      start_frame: 0,
      duration_frames: 24,
      transition_in: {
        type: "none",
        duration_frames: 0,
        overlap_frames: 0,
        accounting: "inside_section",
        audio: "fade_in",
      },
      transition_out: {
        type: "none",
        duration_frames: 0,
        overlap_frames: 0,
        accounting: "inside_section",
        audio: "fade_out",
      },
      assets: [
        {
          asset_id: "asset-1",
          source_key: "asset-1",
          source_sha256: hash("6"),
          provenance_hash: hash("7"),
          caption_hash: hash("8"),
          caption_card: {title: "Prueba • proof"},
          actual_duration_ms: null,
          assigned_duration_ms: null,
          start_frame: 0,
          duration_frames: 24,
          timing_transform: {
            mode: "static_hold",
            source_duration_ms: null,
            output_duration_ms: 1000,
          },
          camera: {mode: "three_complementary_views"},
        },
      ],
      audio: {
        mode: "voice_over",
        sources: [
          {
            source_key: "audio:section-1:0",
            source_sha256: hash("9"),
            source_duration_ms: 1000,
          },
        ],
        timing_transform: {
          mode: "none",
          source_duration_ms: 1000,
          output_duration_ms: 1000,
          atempo_chain: [],
          caption_scale: 1,
        },
        gain_db: 0,
      },
      captions: [
        {
          scene_id: "scene-1",
          text: "Mara: Si puedes oírme.",
          language: {mode: "bilingual", languages: ["es", "en"]},
          section_start_ms: 0,
          section_end_ms: 1000,
          start_frame: 0,
          end_frame: 24,
        },
      ],
    },
  ],
  props_hash: hash("a"),
});

test("schema accepts the exact Python-produced Unicode-safe props hash", () => {
  const parsed = validateCustomFilmRemotionProps(pythonFixture);
  assert.equal(parsed.video.total_frames, 24);
  assert.equal(parsed.sections[0].captions[0].text, "Mara: Si puedes oírme.");
  const {props_hash: propsHash, ...body} = parsed;
  assert.equal(sha256Hex(canonicalJson(body)), propsHash);
  assert.equal(
    sha256Hex("abc"),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
});

test("canonical JSON matches Python Unicode code-point key ordering", () => {
  assert.equal(canonicalJson(unicodeParity.value), unicodeParity.canonical_json);
  assert.equal(
    sha256Hex(canonicalJson(unicodeParity.value)),
    unicodeParity.sha256,
  );
  const tampered = structuredClone(unicodeParity.value);
  tampered["ä"] = "changed";
  assert.notEqual(sha256Hex(canonicalJson(tampered)), unicodeParity.sha256);
});

test("schema rejects unknown fields and an arbitrary regex-valid props hash", () => {
  const unknown = structuredClone(pythonFixture);
  unknown.identity.provider_model = "must-stay-hidden";
  assert.throws(() => validateCustomFilmRemotionProps(unknown));

  const overlap = structuredClone(pythonFixture);
  overlap.sections[0].transition_out.overlap_frames = 1;
  assert.throws(() => validateCustomFilmRemotionProps(overlap));

  const badHash = structuredClone(pythonFixture);
  badHash.sections[0].assets[0].source_sha256 = "not-a-hash";
  assert.throws(() => validateCustomFilmRemotionProps(badHash));

  const arbitrary = structuredClone(pythonFixture);
  arbitrary.props_hash = "a".repeat(64);
  assert.throws(() => validateCustomFilmRemotionProps(arbitrary));
});

test("stale hash rejects caption, media, audio, and identity mutations", () => {
  const mutations = [
    (value) => {
      value.sections[0].captions[0].text = "Tampered caption";
    },
    (value) => {
      value.sections[0].assets[0].source_sha256 = "0".repeat(64);
    },
    (value) => {
      value.sections[0].audio.sources[0].source_sha256 = "0".repeat(64);
    },
    (value) => {
      value.identity.max_spend = 16;
    },
  ];
  for (const mutate of mutations) {
    const changed = structuredClone(pythonFixture);
    mutate(changed);
    assert.throws(() => validateCustomFilmRemotionProps(changed));
  }
});

test("frame math is exact and rejects gaps", () => {
  assert.equal(secondsToFrames(300, 24), 7200);
  const props = structuredClone(pythonFixture);
  assert.doesNotThrow(() =>
    assertExactFrameLayout(props.sections, props.video.total_frames),
  );
  props.sections[0].assets[0].start_frame = 1;
  assert.throws(() =>
    assertExactFrameLayout(props.sections, props.video.total_frames),
  );
});

test("director props require exact shots, measured captions, and sound layers", () => {
  const parsed = validateDirectorRemotionProps(DIRECTOR_FILM_DEFAULT_PROPS);
  assert.equal(parsed.video.total_frames, 72);
  assert.equal(parsed.shots.length, 2);
  assert.equal(parsed.shots[0].performance_mode, "silent_action");
  assert.equal(parsed.shots[1].spoken_lines.length, 2);
  assert.equal(parsed.shots[1].sound_layers[0].kind, "score");
});

test("director props reject timing, dialogue, caption, and gate drift", () => {
  const mutations = [
    (value) => {
      value.shots[1].start_frame = 25;
    },
    (value) => {
      value.shots[1].spoken_lines[1].speaker_id = "hero";
    },
    (value) => {
      value.shots[1].spoken_lines[0].measured_words[0].from_frame = 25;
    },
    (value) => {
      value.shots[0].sound_layers[0].end_frame = 25;
    },
    (value) => {
      value.identity.visual_gate_hash = "f".repeat(64);
    },
  ];
  for (const mutate of mutations) {
    const changed = structuredClone(DIRECTOR_FILM_DEFAULT_PROPS);
    mutate(changed);
    assert.throws(() => validateDirectorRemotionProps(changed));
  }
});

test("scene-control proof locks one environment and two recurring characters across five progressive shots", () => {
  const parsed = validateDirectorRemotionProps(
    DIRECTOR_SCENE_CONTROL_PROOF_PROPS,
  );
  assert.equal(parsed.video.fps, 24);
  assert.equal(parsed.video.total_frames, 432);
  assert.equal(parsed.shots.length, 5);
  assert.deepEqual(
    parsed.shots.map(({start_frame}) => start_frame),
    [0, 72, 168, 240, 336],
  );
  assert.deepEqual(
    parsed.shots.map(({end_frame}) => end_frame),
    [71, 167, 239, 335, 431],
  );

  const characterSets = parsed.shots.map(
    ({continuity}) => continuity?.character_ids,
  );
  assert.ok(characterSets.every(Boolean));
  assert.ok(
    characterSets.every(
      (ids) =>
        JSON.stringify(ids) ===
        JSON.stringify(DIRECTOR_SCENE_CONTROL_LOCKS.character_ids),
    ),
  );
  assert.ok(
    parsed.shots.every(
      ({continuity}) =>
        continuity?.environment_id ===
        DIRECTOR_SCENE_CONTROL_LOCKS.environment_id,
    ),
  );
  assert.ok(
    parsed.shots.every(
      ({continuity}) =>
        continuity?.opening_state !== continuity?.closing_state &&
        Boolean(continuity?.progression),
    ),
  );
});

test("scene-control proof has M/E/M/E measured dialogue, an intentional silent beat, and layered sound", () => {
  const parsed = validateDirectorRemotionProps(
    DIRECTOR_SCENE_CONTROL_PROOF_PROPS,
  );
  const lines = parsed.shots.flatMap(({spoken_lines}) => spoken_lines);
  assert.deepEqual(
    lines.map(({speaker_id}) => speaker_id),
    [
      "scene_control_character_mara",
      "scene_control_character_elias",
      "scene_control_character_mara",
      "scene_control_character_elias",
    ],
  );
  assert.equal(new Set(lines.map(({text}) => text)).size, 4);
  assert.ok(
    lines.every(
      (line) =>
        line.measured_words[0].from_frame === line.start_frame &&
        line.measured_words.at(-1).to_frame === line.end_frame &&
        line.measured_words.map(({text}) => text).join("") === line.text,
    ),
  );

  const silentBeat = parsed.shots[2];
  assert.equal(silentBeat.shot_key, "silent_alarm_beat");
  assert.equal(silentBeat.performance_mode, "silent_action");
  assert.equal(silentBeat.caption_mode, "none");
  assert.equal(silentBeat.spoken_lines.length, 0);

  const kinds = new Set(
    parsed.shots.flatMap(({sound_layers}) =>
      sound_layers.map(({kind}) => kind),
    ),
  );
  assert.deepEqual([...kinds].sort(), ["ambient", "score", "sfx"]);
  assert.ok(
    parsed.shots.every(({sound_layers}) =>
      sound_layers.some(({kind}) => kind === "ambient"),
    ),
  );
});

test("director local sources reject remote, absolute, and traversal paths", () => {
  for (const localPath of [
    "https://provider.example/clip.mp4",
    "file:///tmp/clip.mp4",
    "/tmp/clip.mp4",
    "../clip.mp4",
    "proof/../../clip.mp4",
  ]) {
    const changed = structuredClone(DIRECTOR_SCENE_CONTROL_PROOF_PROPS);
    changed.shots[0].clip.local_path = localPath;
    const {props_hash: _oldHash, ...body} = changed;
    changed.props_hash = sha256Hex(canonicalJson(body));
    assert.throws(() => validateDirectorRemotionProps(changed));
  }
});

test("scene-control props bind every staged clip, voice, ambience, effect, and score byte", () => {
  const parsed = validateDirectorRemotionProps(
    DIRECTOR_SCENE_CONTROL_PROOF_PROPS,
  );
  const sources = parsed.shots.flatMap((shot) => [
    shot.clip,
    ...shot.spoken_lines.map(({source}) => source),
    ...shot.sound_layers.map(({source}) => source),
  ]);
  for (const source of sources) {
    const absolute = path.resolve("public", source.local_path);
    assert.ok(
      fs.existsSync(absolute),
      `staged proof source is missing: ${source.local_path}`,
    );
    const actual = createHash("sha256")
      .update(fs.readFileSync(absolute))
      .digest("hex");
    assert.equal(
      actual,
      source.source_sha256,
      `staged proof source hash changed: ${source.local_path}`,
    );
  }
});

test("scene-control identity is the canonical checked-in control manifest hash chain", () => {
  for (const key of [
    "asset_evidence",
    "director_contract",
    "storyboard_gate",
    "picture_gate",
    "visual_gate",
    "admission",
  ]) {
    assert.equal(
      sha256Hex(canonicalJson(controlManifest[key].payload)),
      controlManifest[key].sha256,
      `${key} canonical evidence changed`,
    );
  }
  assert.equal(
    controlManifest.storyboard_gate.payload.director_contract_hash,
    controlManifest.director_contract.sha256,
  );
  assert.equal(
    controlManifest.picture_gate.payload.storyboard_gate_hash,
    controlManifest.storyboard_gate.sha256,
  );
  assert.equal(
    controlManifest.picture_gate.payload.asset_evidence_hash,
    controlManifest.asset_evidence.sha256,
  );
  assert.equal(
    controlManifest.visual_gate.payload.picture_gate_hash,
    controlManifest.picture_gate.sha256,
  );
  assert.equal(
    controlManifest.admission.payload.visual_gate_hash,
    controlManifest.visual_gate.sha256,
  );
  const {manifest_sha256: manifestHash, ...manifestBody} = controlManifest;
  assert.equal(sha256Hex(canonicalJson(manifestBody)), manifestHash);

  assert.deepEqual(DIRECTOR_SCENE_CONTROL_PROOF_PROPS.identity, {
    director_contract_hash: controlManifest.director_contract.sha256,
    storyboard_gate_hash: controlManifest.storyboard_gate.sha256,
    picture_gate_hash: controlManifest.picture_gate.sha256,
    visual_gate_hash: controlManifest.visual_gate.sha256,
    admission_hash: controlManifest.admission.sha256,
  });
});

test("browser proof package binds the canonical assembly and five playable shot bytes", () => {
  const browserDir = path.resolve(
    "../storyengine/frontend/public/scene-control-proof",
  );
  const browserManifest = JSON.parse(
    fs.readFileSync(path.join(browserDir, "manifest.json"), "utf8"),
  );
  const {
    manifest_sha256: browserManifestHash,
    ...browserManifestBody
  } = browserManifest;
  assert.equal(
    sha256Hex(canonicalJson(browserManifestBody)),
    browserManifestHash,
  );
  assert.equal(
    browserManifest.control_manifest_sha256,
    controlManifest.manifest_sha256,
  );
  assert.deepEqual(
    [
      path.basename(browserManifest.composition.url),
      browserManifest.composition.sha256,
      browserManifest.composition.total_frames,
      browserManifest.composition.duration_seconds,
    ],
    controlManifest.asset_evidence.payload.assembly,
  );
  assert.deepEqual(
    browserManifest.shots.map(({shot_id, sha256}) => [shot_id, sha256]),
    controlManifest.asset_evidence.payload.clips,
  );
  assert.deepEqual(
    browserManifest.shots.map(
      ({start_frame, end_frame, duration_frames}) => [
        start_frame,
        end_frame,
        duration_frames,
      ],
    ),
    [
      [0, 71, 72],
      [72, 167, 96],
      [168, 239, 72],
      [240, 335, 96],
      [336, 431, 96],
    ],
  );
  for (const artifact of [
    browserManifest.composition,
    ...browserManifest.shots,
  ]) {
    const bytes = fs.readFileSync(
      path.join(browserDir, path.basename(artifact.url)),
    );
    assert.equal(
      createHash("sha256").update(bytes).digest("hex"),
      artifact.sha256,
    );
  }
});
