const assert = require("node:assert/strict");
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
